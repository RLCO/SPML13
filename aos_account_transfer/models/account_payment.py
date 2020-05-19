# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math

from odoo import models, fields, api, _
from odoo.tools import float_round, float_is_zero
from odoo.exceptions import UserError, ValidationError
#import openerp.addons.decimal_precision as dp

# class account_abstract_payment(models.AbstractModel):
#     _inherit = "account.abstract.payment"
#      
#     @api.one
#     @api.constrains('amount')
#     def _check_amount(self):
#         #STRING ALLOWED FOR NEGATIVE AMOUNT
#         #if not self.amount > 0.0 and not (self.register_ids or self.settlement_ids or self.other_lines):
#         #    raise ValidationError('The payment amount must be strictly positive.')
#         return

    
class AccountJournal(models.Model):
    _inherit = 'account.journal'

    default_credit_adm_account_id = fields.Many2one('account.account', string='Default Credit Administration Account',
        domain=[('deprecated', '=', False)], help="It acts as a default account for credit amount")
    default_debit_adm_account_id = fields.Many2one('account.account', string='Default Debit Administration Account',
        domain=[('deprecated', '=', False)], help="It acts as a default account for debit amount")
    
    
class account_payment(models.Model):
    _inherit = "account.payment"
    
    #@api.multi
    def _set_invoice_ids(self):
        for payment in self:
            invoice_lines = []
            for register in payment.register_ids:
                invoice_lines += [(4, register.invoice_id.id, None)]
            payment.invoice_ids = invoice_lines
            
#     @api.depends('journal_id')
#     def _compute_branch_id(self):
#         for payment in self:
#             if payment.journal_id:
#                 payment.branch_id = payment.journal_id.branch_id
#                 
#             
#     @api.one
#     def _amount2text_idr(self):
#         for payment in self:
#             if payment.currency_id:
#                 self.check_amount_in_words_id = ''#amount_to_text_id.amount_to_text(math.floor(payment.amount_subtotal), 'id', payment.currency_id.name)
#             else:
#                 self.check_amount_in_words_id = amount_to_text_en.amount_to_text(math.floor(payment.amount_subtotal), lang='en', currency='')
#         return self.check_amount_in_words_id

    @api.depends('partner_id', 'currency_id', 'payment_date')
    def _get_currency_rate(self):
        for payment in self:
            company_currency = payment.journal_id.currency_id or payment.company_id.currency_id
            payment_currency = payment.currency_id or company_currency
            if payment_currency != company_currency:
                payment.force_rate = payment_currency.with_context(partner_id=payment.partner_id.id,date=payment.payment_date).compute(1.0, company_currency, round=False)
            else:
                payment.force_rate = 1.0
                
#     @api.depends('partner_id', 'currency_id', 'date_order', 'is_currency_set')
#     def _get_currency_rate(self):
#         #CurrencyRate = self.env['res.currency.rate']
#         for payment in self:
#             company_currency = payment.company_currency_id
#             payment_currency = payment.currency_id or company_currency
#             if payment_currency != company_currency:
#                 payment.is_multi_currency = True
#                 payment.force_rate = payment_currency.with_context(partner_id=payment.partner_id.id,date=payment.payment_date).compute(1.0, company_currency, round=False)
#             else:
#                 payment.is_multi_currency = False
#                 payment.force_rate = 1.0
#             rate_currency_ids = CurrencyRate.search([('partner_id','=',purchase.partner_id.id),('name','=',purchase.date_order)]).ids
#             if not rate_currency_ids:
#                 rate_currency_ids = CurrencyRate.search([('name','=',purchase.date_order)]).ids
#             #print ('---rate_currency_ids---',purchase.date_order,rate_currency_ids)
#             purchase.currency_rate_ids = rate_currency_ids
    
#     register_date = fields.Date(string='Register Date', required=False, copy=False)
    register_ids = fields.One2many('account.payment.line', 'payment_id', copy=False, string='Register Invoice')
    advance_type = fields.Selection([('invoice', 'Reconcile to Invoice'), 
                                     ('advance', 'Down Payment'), 
                                     ('advance_emp', 'Employee Advance'),
                                     ('receivable_emp','Employee Receivable')], default='invoice', string='Type')
    is_force_curr = fields.Boolean('Kurs Nego')
    #force_rate = fields.Monetary('Kurs Nego Amount')
    #is_currency_set = fields.Boolean('Is Currency Set')
    #is_multi_currency = fields.Boolean('Is Multi Currency', compute='_get_currency_rate', store=True)
    force_rate = fields.Float('Rate Amount', compute='_get_currency_rate', store=True)
    company_currency_id = fields.Many2one('res.currency', string='Company Currency')
    register_date = fields.Date(string='Register Date',  default=fields.Date.context_today, required=False, copy=False)
    state = fields.Selection(selection_add=[('confirm', 'Confirm'),('receipt','Receipt')])
    #payment_difference_handling = fields.Selection(selection_add=[('reconcile_multi', 'Fully paid with another payment')])
    #================make charge transfer=======================================
    amount_charges = fields.Monetary(string='Amount Adm', required=False)
    charge_account_id = fields.Many2one('account.account', string='Account Adm', domain=[('user_type_id.name','=','601.00 Expenses')])
    payment_adm = fields.Selection([
            ('cash','Cash'),
            ('free_transfer','Non Payment Administration Transfer'),
            ('transfer','Transfer'),
            #('check','Check/Giro'),
            #('letter','Letter Credit'),
            ('cc','Credit Card'),
            ('dc','Debit Card'),
            ],string='Payment Adm')
    card_number = fields.Char('Card Number', size=128, required=False)
    card_type = fields.Selection([
            ('visa','Visa'),
            ('master','Master'),
            ('bca','BCA Card'),
            ('citi','CITI Card'),
            ('amex','AMEX'),
            ], string='Card Type', size=128)
    #===========================================================================
    other_lines = fields.One2many('account.payment.other', 'payment_id', string='Payment Lines')
    #===========================================================================
    
    #@api.multi
    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'draft' and self.payment_type == 'transfer':
            return 'aos_account_transfer.mt_transfer_created'
        elif 'state' in init_values and self.state == 'confirm' and self.payment_type == 'transfer':
            return 'aos_account_transfer.mt_transfer_confirm'
        elif 'state' in init_values and self.state == 'sent' and self.payment_type == 'transfer':
            return 'aos_account_transfer.mt_transfer_sent'
        elif 'state' in init_values and self.state == 'receipt' and self.payment_type == 'transfer':
            return 'aos_account_transfer.mt_transfer_receipt'
        return super(account_payment, self)._track_subtype(init_values)
    
    
# 
#     def _get_shared_move_line_vals(self, debit, credit, amount_currency, move_id, invoice_id=False):
#         context = dict(self._context or {})
#         if context.get('charge_counter_id') or context.get('charge_liquidity_id'):
#             res = super(account_payment, self)._get_shared_move_line_vals(credit, debit, amount_currency, move_id, invoice_id)
#             res['name'] = 'BIAYA ADMIN'
#         else:
#             res = super(account_payment, self)._get_shared_move_line_vals(debit, credit, amount_currency, move_id, invoice_id)
#         res['partner_id'] = (self.payment_type in ('inbound', 'outbound') or self.advance_type == 'advance_emp') and self.env['res.partner']._find_accounting_partner(self.partner_id).id or False
#         res['branch_id'] = self.destination_journal_id.branch_id.id or False
#         return res
#     
#     def _get_counterpart_move_line_vals(self, invoice=False):
#         res = super(account_payment, self)._get_counterpart_move_line_vals(invoice=invoice)
#         if invoice and len(invoice) == 1:
#             res['branch_id'] = invoice.branch_id.id or False
#         else:
#             res['branch_id'] = self.branch_id.id or False
#         return res
#     
#     
#     def _get_liquidity_move_line_vals(self, amount):
#         res = super(account_payment, self)._get_liquidity_move_line_vals(amount)
#         res['branch_id'] = self.journal_id.branch_id.id or False
#         return res


    def confirm(self):
        for rec in self:
            if any(line.invoice_id for line in rec.register_ids):
                rec._set_invoice_ids()
            rec.state = 'confirm'
            
    def _get_move_transfer_vals(self, journal=None):
        """ Return dict to create the payment move
        """
        journal = journal or self.journal_id
        if not journal.sequence_id:
            raise UserError(_('Configuration Error !'), _('The journal %s does not have a sequence, please specify one.') % journal.name)
        if not journal.sequence_id.active:
            raise UserError(_('Configuration Error !'), _('The sequence of journal %s is deactivated.') % journal.name)
        name = self.move_name or journal.with_context(ir_sequence_date=self.payment_date).sequence_id.next_by_id()
        return {
            'name': name,
            'date': self.register_date,
            'ref': self.communication or '',
            'company_id': self.company_id.id,
            'journal_id': journal.id,
        }
            
    def _prepare_transfer_moves(self):
#         """ Create a journal entry corresponding to a payment, if the payment references invoice(s) they are reconciled.
#             Return the journal entry.
#         """
#         #=======================================================================
#         # CREATE JURNAL TRANSFER TO CROSS ACCOUNT
#         #=======================================================================
#         aml_obj = self.env['account.move.line'].with_context(check_move_validity=False)
# 
#         debit, credit, amount_currency, currency_id = aml_obj.with_context(date=self.register_date, force_rate=self.force_rate)._compute_amount_fields(amount, self.currency_id, self.company_id.currency_id)
# 
#         move = self.env['account.move'].create(self._get_move_transfer_vals())
#         #Write line corresponding to invoice payment
#         counterpart_aml_dict = self._get_shared_move_line_vals(debit, credit, amount_currency, move.id, False)
#         #print "==self.advance_type==",self._get_counterpart_register_vals(self.register_ids)
#         if self.advance_type == 'advance_emp':
#             counterpart_aml_dict.update(self._get_counterpart_register_vals(self.register_ids))
#         else:
#             counterpart_aml_dict.update(self._get_counterpart_move_line_vals(self.invoice_ids))
#         counterpart_aml_dict.update({'currency_id': currency_id})
#         counterpart_aml = aml_obj.create(counterpart_aml_dict)
#         #Write counterpart lines
#         if not self.currency_id != self.company_id.currency_id:
#             amount_currency = 0
#         liquidity_aml_dict = self._get_shared_move_line_vals(credit, debit, -amount_currency, move.id, False)
#         liquidity_aml_dict.update(self._get_liquidity_move_line_vals(-amount))
#         aml_obj.create(liquidity_aml_dict)
#         #=======================================================================
#         # CREATE JURNAL CHARGE
#         #=======================================================================
#         if self.charge_account_id and self.amount_charges:
#             amount_charges = self.amount_charges
#             charge_debit, charge_credit, charge_amount_currency, currency_id = aml_obj.with_context(date=self.register_date, force_rate=self.force_rate)._compute_amount_fields(-amount_charges, self.currency_id, self.company_id.currency_id)
#             #Write line corresponding to expense charge
#             charge_counterpart_aml_dict = self._get_shared_move_line_vals(charge_debit, charge_credit, charge_amount_currency, move.id, False)
#             charge_counterpart_aml_dict.update(self._get_counterpart_move_line_vals(self.invoice_ids))
#             charge_counterpart_aml_dict.update({'account_id': self.charge_account_id.id, 'currency_id': currency_id})
#             charge_counterpart_aml = aml_obj.create(charge_counterpart_aml_dict)
#             #print "====charge_counterpart_aml_dict===",charge_counterpart_aml_dict
#             #Write counterpart lines with cash/bank account
#             if not self.currency_id != self.company_id.currency_id:
#                 charge_amount_currency = 0
#             charge_liquidity_aml_dict = self._get_shared_move_line_vals(charge_credit, charge_debit, -charge_amount_currency, move.id, False)
#             charge_liquidity_aml_dict.update(self._get_liquidity_move_line_vals(amount_charges))
#             aml_obj.create(charge_liquidity_aml_dict)
#             #print "====charge_liquidity_aml_dict===",charge_liquidity_aml_dict
#         #=======================================================================
#         # POST MOVE
#         #=======================================================================
#         move.post()
#         return move
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

            # Compute amounts.
            counterpart_amount = payment.amount
            liquidity_line_account = payment.journal_id.default_debit_account_id
#             write_off_amount = payment.payment_difference_handling == 'reconcile' and -payment.payment_difference or 0.0
#             if payment.payment_type in ('outbound', 'transfer'):
#                 counterpart_amount = payment.amount
#                 liquidity_line_account = payment.journal_id.default_debit_account_id
#             else:
#                 counterpart_amount = -payment.amount
#                 liquidity_line_account = payment.journal_id.default_credit_account_id

            # Manage currency.
            if payment.currency_id == company_currency:
                # Single-currency.
                balance = counterpart_amount
                #write_off_balance = write_off_amount
                #counterpart_amount = write_off_amount = 0.0
                currency_id = False
                charge_amount_currency = 0.0
            else:
                # Multi-currencies.
                balance = payment.currency_id.with_context(force_rate=payment.force_rate)._convert(counterpart_amount, company_currency, payment.company_id, payment.register_date)
                #write_off_balance = payment.currency_id._convert(write_off_amount, company_currency, payment.company_id, payment.register_date)
                currency_id = payment.currency_id.id
                charge_amount_currency = payment.currency_id.with_context(force_rate=payment.force_rate)._convert(payment.amount_charges, company_currency, payment.company_id, payment.register_date)

            # Manage custom currency on journal for liquidity line.
            if payment.journal_id.currency_id and payment.currency_id != payment.journal_id.currency_id:
                # Custom currency on journal.
                if payment.journal_id.currency_id == company_currency:
                    # Single-currency
                    liquidity_line_currency_id = False
                else:
                    liquidity_line_currency_id = payment.journal_id.currency_id.id
                liquidity_amount = company_currency.with_context(force_rate=payment.force_rate)._convert(
                    balance, payment.journal_id.currency_id, payment.company_id, payment.register_date)
            else:
                # Use the payment currency.
                liquidity_line_currency_id = currency_id
                liquidity_amount = counterpart_amount

            # Compute 'name' to be used in receivable/payable line.
            rec_pay_line_name = payment.name
#             if payment.payment_type == 'transfer':
#                 rec_pay_line_name = payment.name
#             else:
#                 if payment.partner_type == 'customer':
#                     if payment.payment_type == 'inbound':
#                         rec_pay_line_name += _("Customer Payment")
#                     elif payment.payment_type == 'outbound':
#                         rec_pay_line_name += _("Customer Credit Note")
#                 elif payment.partner_type == 'supplier':
#                     if payment.payment_type == 'inbound':
#                         rec_pay_line_name += _("Vendor Credit Note")
#                     elif payment.payment_type == 'outbound':
#                         rec_pay_line_name += _("Vendor Payment")
#                 if payment.invoice_ids:
#                     rec_pay_line_name += ': %s' % ', '.join(payment.invoice_ids.mapped('name'))

            # Compute 'name' to be used in liquidity line.
            liquidity_line_name = _('Transfer to %s') % payment.destination_journal_id.name
#             if payment.payment_type == 'transfer':
#                 liquidity_line_name = _('Transfer to %s') % payment.destination_journal_id.name
#             else:
#                 liquidity_line_name = payment.name

            # ==== 'inbound' / 'outbound' ====

            move_vals = {
                'date': payment.register_date,
                'ref': payment.communication,
                'journal_id': payment.journal_id.id,
                'currency_id': payment.journal_id.currency_id.id or payment.company_id.currency_id.id,
                'partner_id': payment.partner_id.id,
                'line_ids': [
                    # Receivable / Payable / Transfer line.
                    (0, 0, {
                        'name': rec_pay_line_name,
                        'amount_currency': counterpart_amount if currency_id else 0.0,
                        'currency_id': currency_id,
                        'debit': balance > 0.0 and balance or 0.0,
                        'credit': balance < 0.0 and -balance or 0.0,
                        'date_maturity': payment.register_date,
                        'partner_id': payment.partner_id.id,
                        'account_id': payment.company_id.transfer_account_id.id,#payment.destination_account_id.id,
                        'payment_id': payment.id,
                    }),
                    # Liquidity line.
                    (0, 0, {
                        'name': liquidity_line_name,
                        'amount_currency': -liquidity_amount if liquidity_line_currency_id else 0.0,
                        'currency_id': liquidity_line_currency_id,
                        'debit': balance < 0.0 and -balance or 0.0,
                        'credit': balance > 0.0 and balance or 0.0,
                        'date_maturity': payment.register_date,
                        'partner_id': payment.partner_id.id,
                        'account_id': liquidity_line_account.id,
                        'payment_id': payment.id,
                    }),
                ],
            }
#             if write_off_balance:
#                 # Write-off line.
#                 move_vals['line_ids'].append((0, 0, {
#                     'name': payment.writeoff_label,
#                     'amount_currency': -write_off_amount,
#                     'currency_id': currency_id,
#                     'debit': write_off_balance < 0.0 and -write_off_balance or 0.0,
#                     'credit': write_off_balance > 0.0 and write_off_balance or 0.0,
#                     'date_maturity': payment.register_date,
#                     'partner_id': payment.partner_id.id,
#                     'account_id': payment.writeoff_account_id.id,
#                     'payment_id': payment.id,
#                 }))

            if move_names:
                move_vals['name'] = move_names[0]
                
            
            #=======================================================================
            # CREATE JURNAL CHARGE
            #=======================================================================
            if payment.charge_account_id and payment.amount_charges:
                move_vals['line_ids'].append((0, 0, {
                    'name': payment.writeoff_label,
                    'amount_currency': -charge_amount_currency,
                    'currency_id': currency_id,
                    'debit': payment.amount_charges < 0.0 and -payment.amount_charges or 0.0,
                    'credit': payment.amount_charges > 0.0 and payment.amount_charges or 0.0,
                    'date_maturity': payment.register_date,
                    'partner_id': payment.partner_id.id,
                    'account_id': payment.charge_account_id.id,
                    'payment_id': payment.id,
                }))
            all_move_vals.append(move_vals)

            # ==== 'transfer' ====
#             if payment.payment_type == 'transfer':
#                 journal = payment.destination_journal_id
# 
#                 # Manage custom currency on journal for liquidity line.
#                 if journal.currency_id and payment.currency_id != journal.currency_id:
#                     # Custom currency on journal.
#                     liquidity_line_currency_id = journal.currency_id.id
#                     transfer_amount = company_currency._convert(balance, journal.currency_id, payment.company_id, payment.payment_date)
#                 else:
#                     # Use the payment currency.
#                     liquidity_line_currency_id = currency_id
#                     transfer_amount = counterpart_amount
# 
#                 transfer_move_vals = {
#                     'date': payment.payment_date,
#                     'ref': payment.communication,
#                     'partner_id': payment.partner_id.id,
#                     'journal_id': payment.destination_journal_id.id,
#                     'line_ids': [
#                         # Transfer debit line.
#                         (0, 0, {
#                             'name': payment.name,
#                             'amount_currency': -counterpart_amount if currency_id else 0.0,
#                             'currency_id': currency_id,
#                             'debit': balance < 0.0 and -balance or 0.0,
#                             'credit': balance > 0.0 and balance or 0.0,
#                             'date_maturity': payment.payment_date,
#                             'partner_id': payment.partner_id.id,
#                             'account_id': payment.company_id.transfer_account_id.id,
#                             'payment_id': payment.id,
#                         }),
#                         # Liquidity credit line.
#                         (0, 0, {
#                             'name': _('Transfer from %s') % payment.journal_id.name,
#                             'amount_currency': transfer_amount if liquidity_line_currency_id else 0.0,
#                             'currency_id': liquidity_line_currency_id,
#                             'debit': balance > 0.0 and balance or 0.0,
#                             'credit': balance < 0.0 and -balance or 0.0,
#                             'date_maturity': payment.payment_date,
#                             'partner_id': payment.partner_id.id,
#                             'account_id': payment.destination_journal_id.default_credit_account_id.id,
#                             'payment_id': payment.id,
#                         }),
#                     ],
#                 }
# 
#                 if move_names and len(move_names) == 2:
#                     transfer_move_vals['name'] = move_names[1]
# 
#                 all_move_vals.append(transfer_move_vals)
        return all_move_vals

    def _create_payment_entry(self, amount):
        #=======================================================================
        # CHANGE ORIGINAL _create_payment_entry
        #=======================================================================
        """ Create a journal entry corresponding to a payment, if the payment references invoice(s) they are reconciled.
            Return the journal entry.
        """
        #print ('===_create_payment_entry===',self.force_rate)
        aml_obj = self.env['account.move.line'].with_context(check_move_validity=False)
        invoice_currency = self.currency_id
        if self.invoice_ids and all([x.currency_id == self.invoice_ids[0].currency_id for x in self.invoice_ids]):
            #if all the invoices selected share the same currency, record the paiement in that currency too
            invoice_currency = self.invoice_ids[0].currency_id
            #=======================================================================
            # GET RATE FROM INVOICE DATE
            debit_inv, credit_inv, amount_currency_inv, currency_inv_id = aml_obj.with_context(date=self.invoice_ids[0].date_invoice, force_rate=self.force_rate)._compute_amount_fields(amount, invoice_currency, self.company_id.currency_id)
            #=======================================================================
        
        debit, credit, amount_currency, currency_id = aml_obj.with_context(date=self.payment_date, force_rate=self.force_rate)._compute_amount_fields(amount, invoice_currency, self.company_id.currency_id)
        move = self.env['account.move'].create(self._get_move_vals())
        print ('---debit, credit--',self.force_rate,debit, credit,amount_currency)
        #Write line corresponding to invoice payment
        if self.invoice_ids:
            counterpart_aml_dict = self._get_shared_move_line_vals(debit_inv, credit_inv, amount_currency_inv, move.id, False)
        else:
            counterpart_aml_dict = self._get_shared_move_line_vals(debit, credit, amount_currency, move.id, False)
        counterpart_aml_dict.update(self._get_counterpart_move_line_vals(self.invoice_ids))
        counterpart_aml_dict.update({'currency_id': currency_id})
        counterpart_aml = aml_obj.create(counterpart_aml_dict)
        #=======================================================================
        # CREATE EXCHANGE RATE WHEN PAYMENT FORM INVOICE
        #=======================================================================
        if self.invoice_ids and all([x.currency_id == self.invoice_ids[0].currency_id for x in self.invoice_ids]):
            if self.payment_type == 'inbound':
                amount_diff = credit_inv-credit
            elif self.payment_type == 'outbound':
                amount_diff = debit_inv-debit
            if (amount_diff) != 0:
                aml_obj.create({
                    'name': _('Currency exchange rate difference'),
                    'debit': amount_diff > 0 and amount_diff or 0.0,
                    'credit': amount_diff < 0 and -amount_diff or 0.0,
                    'account_id': amount_diff > 0 and self.company_id.currency_exchange_journal_id.default_debit_account_id.id or self.company_id.currency_exchange_journal_id.default_credit_account_id.id,
                    'move_id': move.id,
                    'invoice_id': self.invoice_ids and self.invoice_ids[0].id or False,
                    'payment_id': self.id,
                    'currency_id': False,
                    'amount_currency': 0,
                    'partner_id': self.invoice_ids and self.invoice_ids[0].partner_id.id,
                })
        #===================================================================
        #Reconcile with the invoices
        if self.payment_difference_handling == 'reconcile' and self.payment_difference:
            writeoff_line = self._get_shared_move_line_vals(0, 0, 0, move.id, False)
            amount_currency_wo, currency_id = aml_obj.with_context(date=self.payment_date, force_rate=self.force_rate)._compute_amount_fields(self.payment_difference, invoice_currency, self.company_id.currency_id)[2:]
            # the writeoff debit and credit must be computed from the invoice residual in company currency
            # minus the payment amount in company currency, and not from the payment difference in the payment currency
            # to avoid loss of precision during the currency rate computations. See revision 20935462a0cabeb45480ce70114ff2f4e91eaf79 for a detailed example.
            total_residual_company_signed = sum(invoice.residual_company_signed for invoice in self.invoice_ids)
            total_payment_company_signed = self.currency_id.with_context(date=self.payment_date).compute(self.amount, self.company_id.currency_id)
            if self.invoice_ids[0].type in ['in_invoice', 'out_refund']:
                amount_wo = total_payment_company_signed - total_residual_company_signed
            else:
                amount_wo = total_residual_company_signed - total_payment_company_signed
            debit_wo = amount_wo > 0 and amount_wo or 0.0
            credit_wo = amount_wo < 0 and -amount_wo or 0.0
            writeoff_line['name'] = _('Counterpart')
            writeoff_line['account_id'] = self.writeoff_account_id.id
            writeoff_line['payment_id'] = self.id
            writeoff_line['debit'] = debit_wo
            writeoff_line['credit'] = credit_wo
            writeoff_line['amount_currency'] = amount_currency_wo
            writeoff_line['currency_id'] = currency_id
            writeoff_line = aml_obj.create(writeoff_line)
            if counterpart_aml['debit']:
                counterpart_aml['debit'] += credit_wo - debit_wo
            if counterpart_aml['credit']:
                counterpart_aml['credit'] += debit_wo - credit_wo
            counterpart_aml['amount_currency'] -= amount_currency_wo
        self.invoice_ids.register_payment(counterpart_aml)

        #Write counterpart lines
        if not self.currency_id != self.company_id.currency_id:
            amount_currency = 0
        liquidity_aml_dict = self._get_shared_move_line_vals(credit, debit, -amount_currency, move.id, False)
        liquidity_aml_dict.update(self._get_liquidity_move_line_vals(-amount))
        aml_obj.create(liquidity_aml_dict)
        #=======================================================================
        # CREATE JURNAL CHARGE
        #=======================================================================
        if self.charge_account_id and self.amount_charges:
            #if outbound amount_charges(debit), cash/bank(credit) = minus
            #if inbound amount_charges(credit), cash/bank(credit) = plus
            amount_charges = self.amount_charges
            charge_debit, charge_credit, charge_amount_currency, currency_id = aml_obj.with_context(date=self.register_date, force_rate=self.force_rate)._compute_amount_fields(-amount_charges, self.currency_id, self.company_id.currency_id)
            #Write line corresponding to expense charge
            charge_counterpart_aml_dict = self.with_context(charge_counter_id=True, charge_liquidity_id=False)._get_shared_move_line_vals(charge_debit, charge_credit, self.advance_type == 'cash' and -charge_amount_currency or charge_amount_currency, move.id, False)
            charge_counterpart_aml_dict.update(self.with_context(charge_ref='ADM')._get_counterpart_move_line_vals(self.invoice_ids))
            charge_counterpart_aml_dict.update({'account_id': self.charge_account_id.id, 'currency_id': currency_id})
            charge_counterpart_aml = aml_obj.create(charge_counterpart_aml_dict)
            #Write counterpart lines with cash/bank account
            if not self.currency_id != self.company_id.currency_id:
                charge_amount_currency = 0
            charge_liquidity_aml_dict = self.with_context(charge_counter_id=False, charge_liquidity_id=True)._get_shared_move_line_vals(charge_credit, charge_debit, self.advance_type == 'cash' and charge_amount_currency or -charge_amount_currency, move.id, False)
            charge_liquidity_aml_dict.update(self.with_context(charge_ref='ADM', charge_account_id=True)._get_liquidity_move_line_vals(amount_charges))
            aml_obj.create(charge_liquidity_aml_dict)
        #=======================================================================
        # CREATE JOURNAL OTHER ACCOUNT
        #=======================================================================
        if self.other_lines:
            for other in self.other_lines:
                amount_others = other.amount
                other_debit, other_credit, other_amount_currency, currency_id = aml_obj.with_context(date=self.register_date, force_rate=self.force_rate)._compute_amount_fields(-amount_others, other.currency_id, self.company_id.currency_id)
                #Write line corresponding to expense other
                other_counterpart_aml_dict = self.with_context(other_counter_id=True, other_liquidity_id=False)._get_shared_move_line_vals(other_debit, other_credit, -other_amount_currency, move.id, False)
                other_counterpart_aml_dict.update(self.with_context(other_ref='ADM')._get_counterpart_move_line_vals(self.invoice_ids))
                other_counterpart_aml_dict.update({'account_id': other.account_id.id, 'currency_id': currency_id})
                other_counterpart_aml = aml_obj.create(other_counterpart_aml_dict)
                #Write counterpart lines with cash/bank account
                if not self.currency_id != self.company_id.currency_id:
                    other_amount_currency = 0
                other_liquidity_aml_dict = self.with_context(other_counter_id=False, other_liquidity_id=True)._get_shared_move_line_vals(other_credit, other_debit, other_amount_currency, move.id, False)
                other_liquidity_aml_dict.update(self.with_context(other_ref='ADM', account_id=True)._get_liquidity_move_line_vals(amount_others))
                aml_obj.create(other_liquidity_aml_dict)
        #=======================================================================
        move.post()
        return move
    #===========================================================================
    # internal transfer
    #===========================================================================
    #@api.multi
    def post_transfer(self):
        """ Create the journal items for the payment and update the payment's state to 'posted'.
            A journal entry is created containing an item in the source liquidity account (selected journal's default_debit or default_credit)
            and another in the destination reconciliable account (see _compute_destination_account_id).
            If invoice_ids is not empty, there will be one reconciliable move line per invoice to reconcile with.
            If the payment is a transfer, a second journal entry is created in the destination journal to receive money from the transfer account.
        """
        AccountMove = self.env['account.move'].with_context(default_type='entry')
        for rec in self:
            #CHANGE STATE CONFIRM WHICH CAN BE POSTED
            if rec.state != 'confirm':
                raise UserError(_("Only a confirm transfer can be posted. Trying to post a payment in state %s.") % rec.state)

            # Use the right sequence to set the name
            if not rec.name:
                rec.name = self.env['ir.sequence'].next_by_code('account.payment.transfer', sequence_date=rec.register_date)
                if not rec.name and rec.payment_type != 'transfer':
                    raise UserError(_("You have to define a sequence for %s in your company.") % ('account.payment.transfer',))
            #rec.name = self.env['ir.sequence'].with_context(ir_sequence_date=rec.register_date).next_by_code('account.payment.transfer')

            # Create the journal entry
            #amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
            #move = rec._prepare_transfer_moves(amount)

            # In case of a transfer, the first journal entry created debited the source liquidity account and credited
            # the transfer account. Now we debit the transfer account and credit the destination liquidity account.
            moves = AccountMove.create(rec._prepare_transfer_moves())
            moves.filtered(lambda move: move.journal_id.post_at != 'bank_rec').post()
            move_name = self._get_move_name_transfer_separator().join(moves.mapped('name'))
            rec.write({'state': 'sent', 'move_name': move_name})
            #rec.write({'state': 'sent', 'move_name': move.name})
            
    def _create_transfer_entry(self):
        """ Create the journal entry corresponding to the 'incoming money' part of an internal transfer, return the reconcilable move line
        """
        print ('_create_transfer_entry',self.force_rate)
        #invoice = False
#         aml_obj = self.env['account.move.line'].with_context(check_move_validity=False)
#         debit, credit, amount_currency, dummy = aml_obj.with_context(date=self.payment_date, force_rate=self.force_rate)._compute_amount_fields(amount, self.currency_id, self.company_id.currency_id)
#         amount_currency = self.destination_journal_id.currency_id and self.currency_id.with_context(force_rate=self.force_rate)._convert(amount, self.destination_journal_id.currency_id, self.company_id, self.payment_date or fields.Date.today()) or 0
#         #print ('===amount_currency===',debit, credit, amount_currency)
#         dst_move = self.env['account.move'].create(self._get_move_vals(self.destination_journal_id))
#         
#         dst_liquidity_aml_dict = self._get_shared_move_line_vals(debit, credit, amount_currency, dst_move.id)
#         dst_liquidity_aml_dict.update({
#             'name': _('Transfer from %s') % self.journal_id.name,
#             'account_id': self.destination_journal_id.default_credit_account_id.id,
#             'currency_id': self.destination_journal_id.currency_id.id,
#             'journal_id': self.destination_journal_id.id})
#         aml_obj.create(dst_liquidity_aml_dict)
# 
#         transfer_debit_aml_dict = self._get_shared_move_line_vals(credit, debit, 0, dst_move.id)
#         transfer_debit_aml_dict.update({
#             'name': self.name,
#             'account_id': self.company_id.transfer_account_id.id,
#             'journal_id': self.destination_journal_id.id})
#         if self.currency_id != self.company_id.currency_id:
#             transfer_debit_aml_dict.update({
#                 'currency_id': self.currency_id.id,
#                 'amount_currency': -self.amount,
#             })
#             #print ('--_create_transfer_entry---',amount_currency,self.amount)
# 
#         transfer_debit_aml = aml_obj.create(transfer_debit_aml_dict)
#         if not self.destination_journal_id.post_at_bank_rec:
#             dst_move.post()
#         return transfer_debit_aml
        all_move_vals = []
        for payment in self:
            company_currency = payment.company_id.currency_id
            move_names = payment.move_name.split(payment._get_move_name_transfer_separator()) if payment.move_name else None

            # Compute amounts.
            counterpart_amount = payment.amount
#             write_off_amount = payment.payment_difference_handling == 'reconcile' and -payment.payment_difference or 0.0
#             if payment.payment_type in ('outbound', 'transfer'):
#                 counterpart_amount = payment.amount
#                 liquidity_line_account = payment.journal_id.default_debit_account_id
#             else:
#                 counterpart_amount = -payment.amount
#                 liquidity_line_account = payment.journal_id.default_credit_account_id

            # Manage currency.
            if payment.currency_id == company_currency:
                # Single-currency.
                balance = counterpart_amount
                #write_off_balance = write_off_amount
                counterpart_amount = write_off_amount = 0.0
                currency_id = False
            else:
                # Multi-currencies.
                balance = payment.currency_id.with_context(force_rate=payment.force_rate)._convert(counterpart_amount, company_currency, payment.company_id, payment.payment_date)
                #write_off_balance = payment.currency_id._convert(write_off_amount, company_currency, payment.company_id, payment.payment_date)
                currency_id = payment.currency_id.id

            # Manage custom currency on journal for liquidity line.
#             if payment.journal_id.currency_id and payment.currency_id != payment.journal_id.currency_id:
#                 # Custom currency on journal.
#                 if payment.journal_id.currency_id == company_currency:
#                     # Single-currency
#                     liquidity_line_currency_id = False
#                 else:
#                     liquidity_line_currency_id = payment.journal_id.currency_id.id
#                 liquidity_amount = company_currency._convert(
#                     balance, payment.journal_id.currency_id, payment.company_id, payment.payment_date)
#             else:
#                 # Use the payment currency.
#                 liquidity_line_currency_id = currency_id
#                 liquidity_amount = counterpart_amount

            # Compute 'name' to be used in receivable/payable line.
#             rec_pay_line_name = ''
#             if payment.payment_type == 'transfer':
#                 rec_pay_line_name = payment.name
#             else:
#                 if payment.partner_type == 'customer':
#                     if payment.payment_type == 'inbound':
#                         rec_pay_line_name += _("Customer Payment")
#                     elif payment.payment_type == 'outbound':
#                         rec_pay_line_name += _("Customer Credit Note")
#                 elif payment.partner_type == 'supplier':
#                     if payment.payment_type == 'inbound':
#                         rec_pay_line_name += _("Vendor Credit Note")
#                     elif payment.payment_type == 'outbound':
#                         rec_pay_line_name += _("Vendor Payment")
#                 if payment.invoice_ids:
#                     rec_pay_line_name += ': %s' % ', '.join(payment.invoice_ids.mapped('name'))
# 
#             # Compute 'name' to be used in liquidity line.
#             if payment.payment_type == 'transfer':
#                 liquidity_line_name = _('Transfer to %s') % payment.destination_journal_id.name
#             else:
#                 liquidity_line_name = payment.name
# 
#             # ==== 'inbound' / 'outbound' ====
# 
#             move_vals = {
#                 'date': payment.payment_date,
#                 'ref': payment.communication,
#                 'journal_id': payment.journal_id.id,
#                 'currency_id': payment.journal_id.currency_id.id or payment.company_id.currency_id.id,
#                 'partner_id': payment.partner_id.id,
#                 'line_ids': [
#                     # Receivable / Payable / Transfer line.
#                     (0, 0, {
#                         'name': rec_pay_line_name,
#                         'amount_currency': counterpart_amount + write_off_amount if currency_id else 0.0,
#                         'currency_id': currency_id,
#                         'debit': balance + write_off_balance > 0.0 and balance + write_off_balance or 0.0,
#                         'credit': balance + write_off_balance < 0.0 and -balance - write_off_balance or 0.0,
#                         'date_maturity': payment.payment_date,
#                         'partner_id': payment.partner_id.id,
#                         'account_id': payment.destination_account_id.id,
#                         'payment_id': payment.id,
#                     }),
#                     # Liquidity line.
#                     (0, 0, {
#                         'name': liquidity_line_name,
#                         'amount_currency': -liquidity_amount if liquidity_line_currency_id else 0.0,
#                         'currency_id': liquidity_line_currency_id,
#                         'debit': balance < 0.0 and -balance or 0.0,
#                         'credit': balance > 0.0 and balance or 0.0,
#                         'date_maturity': payment.payment_date,
#                         'partner_id': payment.partner_id.id,
#                         'account_id': liquidity_line_account.id,
#                         'payment_id': payment.id,
#                     }),
#                 ],
#             }
#             if write_off_balance:
#                 # Write-off line.
#                 move_vals['line_ids'].append((0, 0, {
#                     'name': payment.writeoff_label,
#                     'amount_currency': -write_off_amount,
#                     'currency_id': currency_id,
#                     'debit': write_off_balance < 0.0 and -write_off_balance or 0.0,
#                     'credit': write_off_balance > 0.0 and write_off_balance or 0.0,
#                     'date_maturity': payment.payment_date,
#                     'partner_id': payment.partner_id.id,
#                     'account_id': payment.writeoff_account_id.id,
#                     'payment_id': payment.id,
#                 }))
# 
#             if move_names:
#                 move_vals['name'] = move_names[0]
# 
#             all_move_vals.append(move_vals)

            # ==== 'transfer' ====
            if payment.payment_type == 'transfer':
                journal = payment.destination_journal_id

                # Manage custom currency on journal for liquidity line.
                if journal.currency_id and payment.currency_id != journal.currency_id:
                    # Custom currency on journal.
                    liquidity_line_currency_id = journal.currency_id.id
                    transfer_amount = company_currency.with_context(force_rate=payment.force_rate)._convert(balance, journal.currency_id, payment.company_id, payment.payment_date)
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
    
    #@api.multi
    def post_receipt(self):
        """ Create the journal items for the payment and update the payment's state to 'posted'.
            A journal entry is created containing an item in the source liquidity account (selected journal's default_debit or default_credit)
            and another in the destination reconciliable account (see _compute_destination_account_id).
            If invoice_ids is not empty, there will be one reconciliable move line per invoice to reconcile with.
            If the payment is a transfer, a second journal entry is created in the destination journal to receive money from the transfer account.
        """
#         for rec in self:
#             #CHANGE STATE SENT WHICH CAN BE POSTED
#             if rec.state != 'sent':
#                 raise UserError(_("Only a sent transfer can be posted. Trying to post a payment in state %s.") % rec.state)
#  
#             # Use the right sequence to set the name
#             # Use the right sequence to set the name
#             #rec.name = self.env['ir.sequence'].with_context(ir_sequence_date=rec.payment_date).next_by_code('account.payment.transfer')
#  
#             # Create the journal entry
#             amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
#  
#             # In case of a transfer, the first journal entry created debited the source liquidity account and credited
#             # the transfer account. Now we debit the transfer account and credit the destination liquidity account.
#             if rec.payment_type == 'transfer':
#                 transfer_credit_aml = rec.move_line_ids.filtered(lambda r: r.account_id == rec.company_id.transfer_account_id)
#                 transfer_debit_aml = rec._create_transfer_entry(amount)
#                 (transfer_credit_aml + transfer_debit_aml).reconcile()
#  
#             rec.write({'state': 'receipt'})
        AccountMove = self.env['account.move'].with_context(default_type='entry')
        for rec in self:
            #CHANGE STATE CONFIRM WHICH CAN BE POSTED
            if rec.state != 'sent':
                raise UserError(_("Only a sent transfer can be posted. Trying to post a payment in state %s.") % rec.state)

            # Use the right sequence to set the name
#             if not rec.name:
#                 rec.name = self.env['ir.sequence'].next_by_code('account.payment.transfer', sequence_date=rec.register_date)
#                 if not rec.name and rec.payment_type != 'transfer':
#                     raise UserError(_("You have to define a sequence for %s in your company.") % ('account.payment.transfer',))
            #rec.name = self.env['ir.sequence'].with_context(ir_sequence_date=rec.register_date).next_by_code('account.payment.transfer')

            # Create the journal entry
            #amount = rec.amount * (rec.payment_type in ('outbound', 'transfer') and 1 or -1)
            #move = rec._prepare_transfer_moves(amount)

            # In case of a transfer, the first journal entry created debited the source liquidity account and credited
            # the transfer account. Now we debit the transfer account and credit the destination liquidity account.
            moves = AccountMove.create(rec._create_transfer_entry())
            moves.filtered(lambda move: move.journal_id.post_at != 'bank_rec').post()
            #move_name = self._get_move_name_transfer_separator().join(moves.mapped('name'))
            rec.write({'state': 'receipt'})
#             if rec.payment_type in ('inbound', 'outbound'):
#                 # ==== 'inbound' / 'outbound' ====
#                 if rec.invoice_ids:
#                     (moves[0] + rec.invoice_ids).line_ids \
#                         .filtered(lambda line: not line.reconciled and line.account_id == rec.destination_account_id)\
#                         .reconcile()
            if rec.payment_type == 'transfer':
                # ==== 'transfer' ====
                transfer_credit_aml = rec.move_line_ids.filtered(lambda r: r.account_id == rec.company_id.transfer_account_id)
                #transfer_debit_aml = rec._create_transfer_entry(amount)
                transfer_debit_aml = moves.mapped('line_ids').filtered(lambda line: line.account_id == rec.company_id.transfer_account_id)
                (transfer_credit_aml + transfer_debit_aml).reconcile()
            
class account_payment_line(models.Model):
    _name = 'account.payment.line'
    _description = 'Account Payment Line'
    
#     def _compute_total_invoices_amount(self):
#         """ Compute the sum of the residual of invoices, expressed in the payment currency """
#         payment_currency = self.currency_id or self.payment_id.journal_id.currency_id or self.payment_id.journal_id.company_id.currency_id or self.env.user.company_id.currency_id
#         if self.move_line_id.company_id.currency_id != payment_currency:
#             total = self.move_line_id.company_currency_id.with_context(date=self.payment_id.payment_date).compute(self.move_line_id.amount_residual, payment_currency)
#         else:
#             total = self.move_line_id.amount_residual
#         return abs(total)
    
#     @api.one
#     @api.depends('move_line_id', 'invoice_id', 'amount_to_pay', 'payment_id.payment_date', 'currency_id')
#     def _compute_payment_difference(self):
#         self.payment_difference = self._compute_total_invoices_amount() - self.amount_to_pay
#         if self.type == 'dr':
#             self.payment_difference = self._compute_total_invoices_amount() - self.amount_to_pay
#         else:
#             self.payment_difference = self._compute_total_invoices_amount() + self.amount_to_pay
            
#     @api.one
#     @api.depends('invoice_id', 'move_line_id')
#     def _compute_invoice_currency(self):
#         if self.invoice_id and self.invoice_id.currency_id:
#             self.move_currency_id = self.invoice_id.currency_id.id
#         else:
#             self.move_currency_id = self.move_line_id.currency_id.id

    #@api.one
    @api.depends('move_line_id', 'invoice_id', 'amount_total', 'residual', 'amount_to_pay', 'payment_id.payment_date', 'currency_id')
    def _compute_payment_difference(self):
        for line in self:
            line.payment_difference = line.residual - line.amount_to_pay
        
        
    #@api.one
    @api.depends('invoice_id', 'move_line_id')
    def _compute_invoice_currency(self):
        if self.invoice_id and self.invoice_id.currency_id:
            self.move_currency_id = self.invoice_id.currency_id.id
        else:
            self.move_currency_id = self.move_line_id.currency_id.id
            
    move_line_id = fields.Many2one('account.move.line', string='Move Line')
    move_currency_id = fields.Many2one('res.currency', string='Invoice Currency', compute='_compute_invoice_currency',)
    date = fields.Date('Invoice Date')
    date_due = fields.Date('Due Date')
    type = fields.Selection([('dr', 'Debit'),('cr','Credit')], 'Type')
    payment_id = fields.Many2one('account.payment', string='Payment')
    payment_currency_id = fields.Many2one('res.currency', string='Currency')
    currency_id = fields.Many2one('res.currency', related='payment_id.currency_id', string='Currency')
    name = fields.Char(string='Description', required=True)
    invoice_id = fields.Many2one('account.move', string='Invoice')
    amount_total = fields.Float('Original Amount', required=True, digits='Account')
    residual = fields.Float('Outstanding Amount', required=True, digits='Account')
    reconcile = fields.Boolean('Full Payment')
    amount_to_pay = fields.Float('Allocation', required=True, digits='Account')
    statement_line_id = fields.Many2one('account.bank.statement.line', string='Statement Line')
    payment_difference = fields.Monetary(compute='_compute_payment_difference', string='Payment Difference', readonly=True, store=True)
    payment_difference_handling = fields.Selection([('open', 'Keep open'), ('reconcile', 'Mark invoice as fully paid'),
                                                    #('reconcile_multi', 'Fully payment with another payment')
                                                    ], 
                                                   default='open', string="Write-off", copy=False)
    writeoff_account_id = fields.Many2one('account.account', string="Write-off Account", domain=[('deprecated', '=', False)], copy=False)
    to_reconcile = fields.Boolean('To Pay')
    
#     @api.onchange('action')
#     def _onchange_action(self):
#         self.amount_to_pay = self.action and self.residual or 0.0

    @api.onchange('to_reconcile')
    def _onchange_to_reconcile(self):
        if not self.to_reconcile:
            return
        self.amount_to_pay = self.to_reconcile and self.residual or 0.0
        
    def _prepare_statement_line_entry(self, payment, statement):
        #print "===payment===",payment.name
        values = {
            'statement_id': statement.id,
            'payment_line_id': self.id,
            'date': payment.payment_date,
            'name': self.invoice_id.number or self.move_line_id.name or '/', 
            'partner_id': payment.partner_id.id,
            'ref': payment.name,
            'amount': self.amount_to_pay,
        }
        return values
            
class account_payment_other(models.Model):
    _name = 'account.payment.other'
    _description = 'Account Payment Others'
    
    payment_id = fields.Many2one('account.payment', string='Payment')
    name = fields.Char(string='Description', required=True)
    account_id = fields.Many2one('account.account', string='Account',
        required=True, domain=[('deprecated', '=', False),('user_type_id.type','=','other')],
        help="The income or expense account related to the selected product.")
    account_analytic_id = fields.Many2one('account.analytic.account',
        string='Analytic Account')
    currency_id = fields.Many2one('res.currency', string='Currency')
    company_id = fields.Many2one('res.company', string='Company',
        related='payment_id.company_id', store=True, readonly=True)
    amount = fields.Float('Amount', required=True, digits='Account')
    
    @api.onchange('amount')
    def _onchange_amount(self):
        if not self.amount:
            return
        #charge_account_id = self.payment_id.payment_type == 'outbound' and self.payment_id.journal_id.default_debit_adm_account_id.id or self.payment_id.journal_id.default_credit_adm_account_id.id
        self.amount = self.payment_id.payment_type == 'outbound' and -abs(self.amount) or abs(self.amount)
        #self.account_id = charge_account_id
    