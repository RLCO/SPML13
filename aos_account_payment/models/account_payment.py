# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import openerp.addons.decimal_precision as dp

MAP_INVOICE_TYPE_PARTNER_TYPE = {
    'out_invoice': 'customer',
    'out_refund': 'customer',
    'in_invoice': 'supplier',
    'in_refund': 'supplier',
}
# Since invoice amounts are unsigned, this is how we know if money comes in or goes out
MAP_INVOICE_TYPE_PAYMENT_SIGN = {
    'out_invoice': 1,
    'in_refund': 1,
    'in_invoice': -1,
    'out_refund': -1,
}


class AccountPayment(models.Model):
    _inherit = "account.payment"
        
    def _prepare_account_move_line(self, line):
        data = {
            'move_line_id': line.id,
            'date':line.date,
            'date_due':line.date_maturity,
            'type': line.debit and 'dr' or 'cr',
            'invoice_id': line.move_id.id,
            'name': line.move_id.name or line.name or '/',
        }
        company_currency = self.journal_id.company_id.currency_id
        payment_currency = self.currency_id or company_currency
        if line.currency_id and payment_currency==line.currency_id:
            data['amount_total'] = abs(line.amount_currency)
            data['residual'] = abs(line.amount_residual_currency)
            data['amount_to_pay'] = 0.0#abs(line.amount_residual_currency)
        else:
            #always use the amount booked in the company currency as the basis of the conversion into the voucher currency
            data['amount_total'] = company_currency.compute(line.credit or line.debit or 0.0, payment_currency, round=False)#currency_pool.compute(cr, uid, company_currency, voucher_currency, move_line.credit or move_line.debit or 0.0, context=ctx)
            data['residual'] = company_currency.compute(abs(line.amount_residual), payment_currency, round=False)#currency_pool.compute(cr, uid, company_currency, voucher_currency, abs(move_line.amount_residual), context=ctx)
            data['amount_to_pay'] = 0.0#company_currency.compute(abs(line.amount_residual), payment_currency, round=False)#currency_pool.compute(cr, uid, company_currency, voucher_currency, move_line.credit or move_line.debit or 0.0, context=ctx)
        return data
    
    def _set_outstanding_lines(self, partner_id, account_id, currency_id, journal_id, payment_date):
        for payment in self:
            if payment.register_ids:
                payment.register_ids.unlink()
            account_type = None
            if self.payment_type == 'outbound':
                account_type = 'payable'
            else:
                account_type = 'receivable'
            new_lines = self.env['account.payment.line']
            #SEARCH FOR MOVE LINE; RECEIVABLE/PAYABLE AND NOT FULL RECONCILED
            if account_id:
                move_lines = self.env['account.move.line'].search([('account_id','=',account_id.id),('account_id.internal_type','=',account_type),('partner_id','=',partner_id.id),('reconciled','=',False)])
            else:
                move_lines = self.env['account.move.line'].search([('account_id.internal_type','=',account_type),('partner_id','=',partner_id.id),('reconciled','=',False)])
            #print "==_set_outstanding_lines===",move_lines
            for line in move_lines:
                data = payment._prepare_account_move_line(line)
                new_line = new_lines.new(data)
                new_lines += new_line
            payment.register_ids += new_lines
            #'invoice_ids': [(4, inv.id, None) for inv in self._get_invoices()]
            
    @api.depends('payment_type', 'amount', 'amount_charges', 'other_lines')
    def _compute_price(self):
        total_other = 0.0
        for payment in self:
            for oth in payment.other_lines:
                total_other += oth.amount
            if payment.advance_type == 'cash':
                payment.amount_subtotal = payment.amount - payment.amount_charges - total_other
            else:
                payment.amount_subtotal = payment.amount + payment.amount_charges + total_other
            

    def _unlink_invoice_ids(self):
        for payment in self:
            payment.invoice_ids = [(6, 0, [])]
            
    #('draft', 'Draft'), ('posted', 'Posted'), ('sent', 'Sent'), ('reconciled', 'Reconciled')
    #state = fields.Selection(selection_add=[('confirm', 'Confirm')])
    #register_date = fields.Date(string='Register Date', required=False, copy=False)
    payment_date = fields.Date(string='Posted Date', required=False, copy=False)
    force_rate = fields.Float('Rate Amount')
#     name = fields.Char(readonly=True, copy=False)
#     customer_account_id = fields.Many2one('account.account', string='Customer Account', domain=[('reconcile','=',True)])
#     supplier_account_id = fields.Many2one('account.account', string='Supplier Account', domain=[('reconcile','=',True)])
    dest_account_id = fields.Many2one('account.account', string='Dest. Account', domain=[('reconcile','=',True)])
    communication = fields.Char(string='Ref#')
    #register_ids = fields.One2many('account.payment.line', 'payment_id', copy=False, string='Register Invoice')
    residual_account_id = fields.Many2one('account.account', string='Residual Account', domain=[('deprecated','=',False)])
    notes = fields.Text('Notes')
    #amount_subtotal = fields.Monetary(string='Amount', required=True, readonly=True, states={'draft': [('readonly', False)]}, tracking=True)
    amount_subtotal = fields.Float(string='Amount Total',
        store=True, readonly=True, compute='_compute_price', tracking=True)
        
    @api.onchange('destination_journal_id')
    def _onchange_destination_journal_id(self):
        if self.destination_journal_id:
            # Set default payment method (we consider the first to be the default one)
            payment_methods = self.payment_type == 'inbound' and self.destination_journal_id.inbound_payment_method_ids or self.journal_id.outbound_payment_method_ids
            payment_methods_list = payment_methods.ids

            default_payment_method_id = self.env.context.get('default_payment_method_id')
            if default_payment_method_id:
                # Ensure the domain will accept the provided default value
                payment_methods_list.append(default_payment_method_id)
            else:
                self.payment_method_id = payment_methods and payment_methods[0] or False

            # Set payment method domain (restrict to methods enabled for the journal and to selected payment type)
            payment_type = self.payment_type in ('outbound', 'transfer') and 'outbound' or 'inbound'
            return {'domain': {'payment_method_id': [('payment_type', '=', payment_type), ('id', 'in', payment_methods_list)]}}
        return {}
    
    @api.onchange('register_ids')
    def _onchange_register_ids(self):
        amount = amount_subtotal = 0.0
        for line in self.register_ids:
            #if line.action:
            amount += line.amount_to_pay
#         total_other = 0.0
#         for oth in self.other_lines:
#             total_other += oth.amount
#         if self.advance_type == 'cash':
#             amount_subtotal = amount - self.amount_charges - total_other
#         else:
#             amount_subtotal = amount + self.amount_charges + total_other
        self.amount = amount
#         self.amount_subtotal = amount_subtotal
        return
    
    #@api.multi
    def button_outstanding(self):
        #print "==button_outstanding=="
        for payment in self:
            account_id = payment.dest_account_id or False
            if payment.partner_id and payment.currency_id and payment.journal_id and payment.payment_date:
                #payment._set_currency_rate()
                payment._set_outstanding_lines(payment.partner_id, account_id, payment.currency_id, payment.journal_id, payment.payment_date)
                #payment._set_invoice_ids()
                #print "===payment==",payment.register_ids
                #payment.invoice_ids = [(4, reg.invoice_id.id, None) for reg in payment.register_ids()]
         
    @api.model
    def default_get(self, fields):
        rec = super(AccountPayment, self).default_get(fields)
        invoice_defaults = self.resolve_2many_commands('invoice_ids', rec.get('invoice_ids'))
        #print "===checkline_defaults===",checkline_defaults
        if invoice_defaults and len(invoice_defaults) == 1:
            invoice = invoice_defaults[0]
            #print "===default===",invoice['sale_id'],invoice['number']#,invoice['sale_id']['name'],invoice['number']
            if 'sale_id' in invoice:
                communication = invoice['sale_id'] and invoice['name'] + ':' + invoice['sale_id'][1]
            else:
                communication = invoice['name']
            rec['communication'] = communication
            rec['currency_id'] = invoice['currency_id'][0]
            rec['payment_type'] = invoice['type'] in ('out_invoice', 'in_refund') and 'inbound' or 'outbound'
            rec['partner_type'] = MAP_INVOICE_TYPE_PARTNER_TYPE[invoice['type']]
            rec['partner_id'] = invoice['partner_id'][0]
            rec['amount'] = invoice['amount_residual']
        return rec
    
    #@api.one
    @api.depends('invoice_ids', 'payment_type', 'partner_type', 'partner_id', 
                 #'customer_account_id', 'supplier_account_id'
                 'dest_account_id')
    def _compute_destination_account_id(self):
        for payment in self:
            if payment.invoice_ids:
                payment.destination_account_id = payment.invoice_ids[0].mapped(
                    'line_ids.account_id').filtered(
                        lambda account: account.user_type_id.type in ('receivable', 'payable'))[0]
            elif payment.payment_type == 'transfer':
                if payment.advance_type == 'advance_emp':
                    payment.destination_account_id = payment.dest_account_id and payment.dest_account_id.id
                else:
                    if payment.company_id.transfer_account_id.id:
                        raise UserError(_('There is no Transfer Account defined in the accounting settings. Please define one to be able to confirm this transfer.'))
                    payment.destination_account_id = payment.company_id.transfer_account_id.id
            elif payment.partner_id:
                if payment.partner_type == 'customer':
                    #payment.destination_account_id = payment.partner_id.property_account_receivable_id.id
                    if payment.advance_type == 'advance':
                        payment.destination_account_id = payment.dest_account_id and payment.dest_account_id.id or payment.partner_id.property_account_advance_receivable_id and payment.partner_id.property_account_advance_receivable_id.id
                    else:
                        payment.destination_account_id = payment.dest_account_id and payment.dest_account_id.id or payment.partner_id.property_account_receivable_id and payment.partner_id.property_account_receivable_id.id
                elif payment.partner_type == 'supplier':
                    if payment.advance_type == 'advance':
                        payment.destination_account_id = payment.dest_account_id and payment.dest_account_id.id or payment.partner_id.property_account_advance_payable_id and payment.partner_id.property_account_advance_payable_id.id
                    else:
                        payment.destination_account_id = payment.dest_account_id and payment.dest_account_id.id or payment.partner_id.property_account_payable_id and payment.partner_id.property_account_payable_id.id
                else:
                    if payment.advance_type == 'advance_emp':
                        payment.destination_account_id = payment.destination_journal_id.default_credit_account_id.id
                    else:
                        payment.destination_account_id = payment.partner_id.property_account_payable_id.id
            elif payment.partner_type == 'customer':
                default_account = self.env['ir.property'].get('property_account_receivable_id', 'res.partner')
                payment.destination_account_id = default_account.id
            elif payment.partner_type == 'supplier':
                default_account = self.env['ir.property'].get('property_account_payable_id', 'res.partner')
                payment.destination_account_id = default_account.id
                
                
    @api.onchange('destination_journal_id')
    def _onchange_destination_journal(self):
        if self.destination_journal_id:
            self.destination_account_id = self.destination_journal_id.default_debit_account_id and self.destination_journal_id.default_debit_account_id.id or self.destination_journal_id.default_credit_account_id or self.destination_journal_id.default_debit_account_id.id or False               
    
    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        res = super(AccountPayment, self)._onchange_payment_type()
        return res
    
#     def _get_shared_move_line_vals(self, debit, credit, amount_currency, move_id, invoice_id=False):
#         context = dict(self._context or {})
#         if context.get('charge_counter_id') or context.get('charge_liquidity_id'):
#             res = super(AccountPayment, self)._get_shared_move_line_vals(credit, debit, amount_currency, move_id, invoice_id)
#             res['name'] = 'BIAYA ADMIN'
#         else:
#             res = super(AccountPayment, self)._get_shared_move_line_vals(debit, credit, amount_currency, move_id, invoice_id)
#         res['partner_id'] = (self.payment_type in ('inbound', 'outbound') or self.advance_type == 'advance_emp') and self.env['res.partner']._find_accounting_partner(self.partner_id).id or False
#         return res
    
    #@api.multi
    def action_cancel(self):
        for rec in self:
            rec._unlink_invoice_ids()
            rec.cancel()
            #rec.state = 'draft'
            
    def action_validate_invoice_payment(self):
        """ Posts a payment used to pay an invoice. This function only posts the
        payment by default but can be overridden to apply specific post or pre-processing.
        It is called by the "validate" button of the popup window
        triggered on invoice form by the "Register Payment" button.
        """
        #if any(len(record.invoice_ids) != 1 for record in self):
        #    # For multiple invoices, there is account.register.payments wizard
        #    raise UserError(_("This method should only be called to process a single invoice's payment."))
        return self.post()
    
            
    def post(self):
        """ Create the journal items for the payment and update the payment's state to 'posted'.
            A journal entry is created containing an item in the source liquidity account (selected journal's default_debit or default_credit)
            and another in the destination reconcilable account (see _compute_destination_account_id).
            If invoice_ids is not empty, there will be one reconcilable move line per invoice to reconcile with.
            If the payment is a transfer, a second journal entry is created in the destination journal to receive money from the transfer account.
        """
        AccountMove = self.env['account.move'].with_context(default_type='entry')
        for rec in self:

            #if rec.state != 'draft':
            #    raise UserError(_("Only a draft payment can be posted."))

            if any(inv.state != 'posted' for inv in rec.invoice_ids):
                raise ValidationError(_("The payment cannot be processed because the invoice is not open!"))

            # keep the name in case of a payment reset to draft
            if not rec.name:
                # Use the right sequence to set the name
                if rec.payment_type == 'transfer':
                    sequence_code = 'account.payment.transfer'
                else:
                    if rec.partner_type == 'customer':
                        if rec.payment_type == 'inbound':
                            sequence_code = 'account.payment.customer.invoice'
                        if rec.payment_type == 'outbound':
                            sequence_code = 'account.payment.customer.refund'
                    if rec.partner_type == 'supplier':
                        if rec.payment_type == 'inbound':
                            sequence_code = 'account.payment.supplier.refund'
                        if rec.payment_type == 'outbound':
                            sequence_code = 'account.payment.supplier.invoice'
                rec.name = self.env['ir.sequence'].next_by_code(sequence_code, sequence_date=rec.payment_date)
                if not rec.name and rec.payment_type != 'transfer':
                    raise UserError(_("You have to define a sequence for %s in your company.") % (sequence_code,))
            if not rec.register_ids:
                #amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
                #move = rec._create_payment_entry(amount)
                moves = AccountMove.create(rec._prepare_payment_moves())
                moves.filtered(lambda move: move.journal_id.post_at != 'bank_rec').post()
            else:
                #===================================================================
                move_vals = rec._prepare_payment_move()[0]
                total_amount = 0.0
                #move_ids_vals = []
                invoice_ids = []
                move_iline = []
                for line in rec.register_ids:
                    #create receivable or payable each invoice
                    if line.amount_to_pay != 0:
                        move_iline += rec._prepare_payment_moves_multi(line.amount_to_pay * (rec.payment_type in ('outbound', 'transfer') and 1 or -1), move_vals, line)
                        invoice_ids.append(line.invoice_id.id)
                        #rec.invoice_ids = [(6, 0, line.invoice_id.ids)]
                        total_amount += (line.amount_to_pay * (rec.payment_type in ('outbound', 'transfer') and -1 or 1))
                rec.invoice_ids = [(6, 0, invoice_ids)]
                iline_liquidity = rec._create_liquidity_entry(-rec.amount * (rec.payment_type in ('outbound', 'transfer') and -1 or 1), total_amount+rec.amount, move_vals)
                moves = AccountMove.create(iline_liquidity)
                moves.filtered(lambda move: move.journal_id.post_at != 'bank_rec').post()

            # Update the state / move before performing any reconciliation.
            move_name = self._get_move_name_transfer_separator().join(moves.mapped('name'))
            rec.write({'state': 'posted', 'move_name': move_name})
            #print ('--moves--',moves.line_ids)
            if rec.payment_type in ('inbound', 'outbound'):
                # ==== 'inbound' / 'outbound' ====
                if rec.invoice_ids:
                    (moves[0] + rec.invoice_ids).line_ids \
                        .filtered(lambda line: not line.reconciled and line.account_id == rec.destination_account_id)\
                        .reconcile()
            elif rec.payment_type == 'transfer':
                # ==== 'transfer' ====
                moves.mapped('line_ids')\
                    .filtered(lambda line: line.account_id == rec.company_id.transfer_account_id)\
                    .reconcile()

        return True
            
            
            
    def _get_counterpart_move_line_vals(self, invoice=False):
        res = super(AccountPayment, self)._get_counterpart_move_line_vals(invoice=invoice)
        #print "-----self.destination_account_id----",invoice,self,self.destination_account_id
        if invoice and len(invoice) == 1:
            res['account_id'] = invoice.account_id and invoice.account_id.id or self.destination_account_id and self.destination_account_id.id
        return res
    
    
    #@api.multi
    def post_multi(self):
        """ Create the journal items for the payment and update the payment's state to 'posted'.
            A journal entry is created containing an item in the source liquidity account (selected journal's default_debit or default_credit)
            and another in the destination reconciliable account (see _compute_destination_account_id).
            If invoice_ids is not empty, there will be one reconciliable move line per invoice to reconcile with.
            If the payment is a transfer, a second journal entry is created in the destination journal to receive money from the transfer account.
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a draft payment can be posted. Trying to post a payment in state %s.") % rec.state)

            if any(inv.state != 'open' for inv in rec.invoice_ids):
                raise ValidationError(_("The payment cannot be processed because the invoice is not open!"))

            # Use the right sequence to set the name
            if rec.payment_type == 'transfer':
                sequence_code = 'account.payment.transfer'
            else:
                if rec.partner_type == 'customer':
                    if rec.payment_type == 'inbound':                        
                        if rec.advance_type == 'advance':
                            sequence_code = 'account.payment.customer.advance'
                        else:
                            sequence_code = 'account.payment.customer.invoice'
                    if rec.payment_type == 'outbound':
                        sequence_code = 'account.payment.customer.refund'
                if rec.partner_type == 'supplier':
                    if rec.payment_type == 'inbound':
                        sequence_code = 'account.payment.supplier.refund'
                    if rec.payment_type == 'outbound':
                        if rec.advance_type == 'advance':
                            sequence_code = 'account.payment.supplier.advance'
                        else:
                            sequence_code = 'account.payment.supplier.invoice'
                            
            rec.name = self.env['ir.sequence'].with_context(ir_sequence_date=rec.payment_date).next_by_code(sequence_code)
            
            # Create the journal entry
            if not rec.register_ids:
                amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
                move = rec._create_payment_entry(amount)
            else:
                #===================================================================
                amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
                move = self.env['account.move'].create(self._get_move_vals())                
                total_amount = 0.0
                for line in rec.register_ids:
                    #create receivable or payable each invoice
                    if line.amount_to_pay != 0:
                        rec._create_payment_entry_multi(line.amount_to_pay * (rec.payment_type in ('outbound', 'transfer') and 1 or -1), line.invoice_id, move, line)
                    total_amount += (line.amount_to_pay * (rec.payment_type in ('outbound', 'transfer') and -1 or 1))
                #TOTAL AMOUNT
                #print ('--amount-',amount,total_amount)
                rec._create_liquidity_entry(-amount, total_amount+amount, move)
#                 if amount + total_amount:
#                     rec._create_payment_entry_difference(amount + total_amount, move)
            #===================================================================
            # In case of a transfer, the first journal entry created debited the source liquidity account and credited
            # the transfer account. Now we debit the transfer account and credit the destination liquidity account.
            if rec.payment_type == 'transfer':
                transfer_credit_aml = move.line_ids.filtered(lambda r: r.account_id == rec.company_id.transfer_account_id)
                transfer_debit_aml = rec._create_transfer_entry(amount)
                (transfer_credit_aml + transfer_debit_aml).reconcile()
            rec.write({'state': 'posted', 'move_name': move.name})
            
    def _prepare_payment_move(self):
        all_move_vals = []
        for payment in self:
            #company_currency = payment.company_id.currency_id
            move_names = payment.move_name.split(payment._get_move_name_transfer_separator()) if payment.move_name else None
            #print ('---move_names--',move_names)
            move_vals = {
                'date': payment.payment_date,
                'ref': payment.communication,
                'journal_id': payment.journal_id.id,
                'currency_id': payment.journal_id.currency_id.id or payment.company_id.currency_id.id,
                'partner_id': payment.partner_id.id,
                'line_ids': [],
            }
            
            if move_names:
                move_vals['name'] = move_names[0]

            all_move_vals.append(move_vals)
        return all_move_vals
    
    def _prepare_payment_moves_multi(self, amount, move_vals, line):
        ''' Prepare the creation of journal entries (account.move) by creating a list of python dictionary to be passed
        to the 'create' method.

        Example 1: outbound with write-off:

        Account             | Debit     | Credit
        ---------------------------------------------------------
        BANK                |   900.0   |
        RECEIVABLE          |           |   1000.0
        WRITE-OFF ACCOUNT   |   100.0   |

        Example 2: internal transfer from BANK to CASH:

        Account             | Debit     | Credit
        ---------------------------------------------------------
        BANK                |           |   1000.0
        TRANSFER            |   1000.0  |
        CASH                |   1000.0  |
        TRANSFER            |           |   1000.0

        :return: A list of Python dictionary to be passed to env['account.move'].create.
        '''
        all_move_vals = []
        for payment in self:
            company_currency = payment.company_id.currency_id
            move_names = payment.move_name.split(payment._get_move_name_transfer_separator()) if payment.move_name else None

            # Compute amounts.if line.payment_difference and line.writeoff_account_id:
            #write_off_amount = payment.payment_difference_handling == 'reconcile' and -payment.payment_difference or 0.0
            write_off_amount = -line.payment_difference or 0.0
            counterpart_amount = amount
            
            if payment.currency_id == company_currency:
                # Single-currency.
                balance = counterpart_amount
                write_off_balance = write_off_amount
                counterpart_amount = write_off_amount = 0.0
                currency_id = False
            else:
                # Multi-currencies.
                balance = payment.currency_id._convert(counterpart_amount, company_currency, payment.company_id, payment.payment_date)
                write_off_balance = payment.currency_id._convert(write_off_amount, company_currency, payment.company_id, payment.payment_date)
                currency_id = payment.currency_id.id

            # Manage custom currency on journal for liquidity line.
            if payment.journal_id.currency_id and payment.currency_id != payment.journal_id.currency_id:
                # Custom currency on journal.
                if payment.journal_id.currency_id == company_currency:
                    # Single-currency
                    liquidity_line_currency_id = False
                else:
                    liquidity_line_currency_id = payment.journal_id.currency_id.id
            else:
                # Use the payment currency.
                liquidity_line_currency_id = currency_id

            # Compute 'name' to be used in receivable/payable line.
            rec_pay_line_name = ''
            move_vals['line_ids'].append((0, 0, {
                'name': rec_pay_line_name,
                'amount_currency': counterpart_amount + write_off_amount if currency_id else 0.0,
                'currency_id': currency_id,
                'debit': balance + write_off_balance > 0.0 and balance + write_off_balance or 0.0,
                'credit': balance + write_off_balance < 0.0 and -balance - write_off_balance or 0.0,
                'date_maturity': payment.payment_date,
                'partner_id': payment.partner_id.id,
                'account_id': payment.destination_account_id.id,
                'payment_id': payment.id,
            }))
            
            if write_off_balance:
                # Write-off line.
                move_vals['line_ids'].append((0, 0, {
                    'name': payment.writeoff_label or 'Write-off',
                    'amount_currency': -write_off_amount,
                    'currency_id': currency_id,
                    'debit': write_off_balance < 0.0 and -write_off_balance or 0.0,
                    'credit': write_off_balance > 0.0 and write_off_balance or 0.0,
                    'date_maturity': payment.payment_date,
                    'partner_id': payment.partner_id.id,
                    'account_id': line.writeoff_account_id.id,
                    'payment_id': payment.id,
                }))
                
            all_move_vals.append(move_vals)
            # ==== 'transfer' ====
            if payment.payment_type == 'transfer':
                journal = payment.destination_journal_id

                # Manage custom currency on journal for liquidity line.
                if journal.currency_id and payment.currency_id != journal.currency_id:
                    # Custom currency on journal.
                    liquidity_line_currency_id = journal.currency_id.id
                    transfer_amount = company_currency._convert(balance, journal.currency_id, payment.company_id, payment.payment_date)
                else:
                    # Use the payment currency.
                    liquidity_line_currency_id = currency_id
                    transfer_amount = counterpart_amount
                transfer_move_vals = {
                    'date': payment.payment_date,
                    'ref': payment.communication,
                    'partner_id': payment.partner_id.id,
                    'journal_id': payment.destination_journal_id.id,
                    'line_ids': [
                        # Transfer debit line.
                        (0, 0, {
                            'name': payment.name,
                            'amount_currency': -counterpart_amount if currency_id else 0.0,
                            'currency_id': currency_id,
                            'debit': balance < 0.0 and -balance or 0.0,
                            'credit': balance > 0.0 and balance or 0.0,
                            'date_maturity': payment.payment_date,
                            'partner_id': payment.partner_id.id,
                            'account_id': payment.company_id.transfer_account_id.id,
                            'payment_id': payment.id,
                        }),
                        # Liquidity credit line.
                        (0, 0, {
                            'name': _('Transfer from %s') % payment.journal_id.name,
                            'amount_currency': transfer_amount if liquidity_line_currency_id else 0.0,
                            'currency_id': liquidity_line_currency_id,
                            'debit': balance > 0.0 and balance or 0.0,
                            'credit': balance < 0.0 and -balance or 0.0,
                            'date_maturity': payment.payment_date,
                            'partner_id': payment.partner_id.id,
                            'account_id': payment.destination_journal_id.default_credit_account_id.id,
                            'payment_id': payment.id,
                        }),
                    ],
                }

                if move_names and len(move_names) == 2:
                    transfer_move_vals['name'] = move_names[1]

                all_move_vals.append(transfer_move_vals)           
                
        return all_move_vals
    
#     def _get_counterpart_register_vals(self, registers=False):
#         name = ''
#         if registers:
#             name += ''
#             for reg in registers:
#                 if reg.name:
#                     name += reg.name + ', '
#             name = name[:len(name)-2] 
#         return {
#             'name': name,
#             'account_id': self.destination_account_id.id,
#             'journal_id': self.journal_id.id,
#             'currency_id': self.currency_id != self.company_id.currency_id and self.currency_id.id or False,
#             'payment_id': self.id,
#         }
    
    def _create_liquidity_entry(self, amount, amount_diff, move_vals):
        """ def _create_liquidity_entry_aos for total liquidity received or paid"""
        all_move_vals = []
        for payment in self:
            company_currency = payment.company_id.currency_id
            #move_names = payment.move_name.split(payment._get_move_name_transfer_separator()) if payment.move_name else None
            counterpart_amount = amount
            liquidity_line_account = payment.journal_id.default_debit_account_id if counterpart_amount>0.0 else payment.journal_id.default_credit_account_id
            
            # Manage currency.
            if payment.currency_id == company_currency:
                # Single-currency.
                balance = counterpart_amount
                #write_off_balance = write_off_amount
                counterpart_amount = write_off_amount = 0.0
                currency_id = False
            else:
                # Multi-currencies.
                balance = payment.currency_id._convert(counterpart_amount, company_currency, payment.company_id, payment.payment_date)
                #write_off_balance = payment.currency_id._convert(write_off_amount, company_currency, payment.company_id, payment.payment_date)
                currency_id = payment.currency_id.id

            # Manage custom currency on journal for liquidity line.
            if payment.journal_id.currency_id and payment.currency_id != payment.journal_id.currency_id:
                # Custom currency on journal.
                if payment.journal_id.currency_id == company_currency:
                    # Single-currency
                    liquidity_line_currency_id = False
                else:
                    liquidity_line_currency_id = payment.journal_id.currency_id.id
                liquidity_amount = company_currency._convert(
                    balance, payment.journal_id.currency_id, payment.company_id, payment.payment_date)
            else:
                # Use the payment currency.
                liquidity_line_currency_id = currency_id
                liquidity_amount = counterpart_amount

            # Compute 'name' to be used in liquidity line.
            if payment.payment_type == 'transfer':
                liquidity_line_name = _('Transfer to %s') % payment.destination_journal_id.name
            else:
                liquidity_line_name = payment.name

            move_vals['line_ids'].append((0, 0, {
                    'name': liquidity_line_name,
                    'amount_currency': -liquidity_amount if liquidity_line_currency_id else 0.0,
                    'currency_id': liquidity_line_currency_id,
                    'debit': balance < 0.0 and -balance or 0.0,
                    'credit': balance > 0.0 and balance or 0.0,
                    'date_maturity': payment.payment_date,
                    'partner_id': payment.partner_id.id,
                    'account_id': liquidity_line_account.id,
                    'payment_id': payment.id,
            }))
            
            all_move_vals.append(move_vals)
        return all_move_vals
    
    