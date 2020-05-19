# -*- coding: utf-8 -*-
import math
from openerp import models, fields, api, _
from openerp.exceptions import UserError, ValidationError
#import openerp.addons.decimal_precision as dp

class account_register_payments(models.TransientModel):
    _inherit = "account.payment.register"
    
    def _get_register_invoices(self):
        return self.env['account.move'].browse(self._context.get('active_ids'))
    
    def _get_register_lines(self, register_ids):
        registers = []
        if register_ids:
            for register in register_ids:
                registers.append(register.id)
        return self.env['account.register.line'].browse(registers)
    
#     def _set_currency_rate(self):
#         if self.is_force_curr:
#             company_currency = self.journal_id.company_id.currency_id
#             payment_currency = self.currency_id or company_currency
#             self.force_rate = payment_currency.with_context(date=self.payment_date).compute(1.0, company_currency, round=False)
#             self.company_currency_id = company_currency.id
#         else:
#             self.force_rate = 0.0
    
#     company_currency_id = fields.Many2one('res.currency', string='Company Currency')
#     is_force_curr = fields.Boolean('Kurs Nego')
#     force_rate = fields.Monetary('Kurs Nego Amount')
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
    register_ids = fields.One2many('account.register.line', 'register_id', copy=False, string='Register Invoice')
    
#     @api.model
#     def default_get(self, fields):
#         rec = super(account_register_payments, self).default_get(fields)
#         context = dict(self._context or {})
#         active_model = context.get('active_model')
#         active_ids = context.get('active_ids')
#          
#         reg_lines = []
#         communication = []
#         for invoice in self.env[active_model].browse(active_ids):
#             communication.append(invoice.name)
#             reg_lines.append([0, 0, {
#                'invoice_id': invoice.id,
#                'name': invoice.name,
#                'amount_total': invoice.amount_total,
#                'residual': invoice.amount_residual,
#                'amount_to_pay': invoice.amount_residual,
#                }])
#         rec.update({
#             'register_ids': reg_lines,
#             'communication': ", ".join(communication),
#         })
#         #print ("===rec===",rec)
#         return rec
    
#     @api.onchange('journal_id', 'amount')
#     def _onchange_journal_id(self):
#         if self.journal_id:
#             company_currency = self.journal_id.company_id.currency_id
#             payment_currency = self.currency_id or company_currency
#             if company_currency == payment_currency:
#                 self.is_force_curr = False
#                 self.force_rate = 0.0

#     @api.onchange('is_force_curr','payment_date')
#     def _onchange_is_force_curr(self):
#         self._set_currency_rate()
    
    @api.onchange('register_ids')
    def _onchange_register_ids(self):
        amount = 0.0
        for line in self.register_ids:
            amount += line.amount_to_pay
        self.amount = amount
        return
    
#     def get_payment_line_vals(self, payment, line):
#         """ Hook for extension """
#         return {
#             'payment_id': payment.id,
#             'name': line.name,
#             'invoice_id': line.invoice_id.id,
#             #'type': line.debit and 'dr' or 'cr',
#             'amount_total': line.amount_total,
#             'residual': line.residual,
#             'amount_to_pay': line.amount_to_pay,
#             'payment_difference': line.payment_difference,
#             'payment_difference_handling': line.payment_difference_handling,
#             'writeoff_account_id': line.writeoff_account_id and line.writeoff_account_id.id or False,
#         }

    def get_payment_line_vals(self, payment, line):
        #print (""" Hook for extension """,line.residual,line.amount_total,line.amount_to_pay,self.amount)
        return {
            'to_reconcile': line.residual == line.amount_to_pay,
            'payment_id': payment.id,
            'name': line.name,
            'invoice_id': line.invoice_id.id,
            'date': line.invoice_id.date_invoice,
            'date_due': line.invoice_id.date_due or False,
            'move_line_id': line.invoice_id.move_id.line_ids.filtered(lambda x: x.account_id == line.invoice_id.account_id).id,
            'type': line.invoice_id.type in ['in_invoice', 'out_refund'] and 'cr' or 'dr',
            'amount_total': line.amount_total,
            'residual': line.residual,
            'amount_to_pay': line.amount_to_pay,
            'payment_difference': line.payment_difference,
            'payment_difference_handling': line.payment_difference_handling,
            'writeoff_account_id': line.writeoff_account_id and line.writeoff_account_id.id or False,
        }
        
    #@api.multi
    def _prepare_payment_vals(self, invoices):
        '''Create the payment values.

        :param invoices: The invoices that should have the same commercial partner and the same type.
        :return: The payment values as a dictionary.
        '''
        res = super(account_register_payments, self)._prepare_payment_vals(invoices)
#         print ('===res===',res,self)
#         for line in self._get_register_lines(self.register_ids):
#             self.env['account.payment.line'].create(self.get_payment_line_vals(self, line))
        res['payment_adm'] = self.payment_adm
        #res['is_force_curr'] = self.is_force_curr
        #res['force_rate'] = self.force_rate
        res['card_number'] = self.card_number
        res['card_type'] = self.card_type
        return res
    
    #@api.multi
    def create_payments(self):
        '''Create payments according to the invoices.
        Having invoices with different commercial_partner_id or different type (Vendor bills with customer invoices)
        leads to multiple payments.
        In case of all the invoices are related to the same commercial_partner_id and have the same type,
        only one payment will be created.

        :return: The ir.actions.act_window to show created payments.
        '''
        Payment = self.env['account.payment']
        payments = Payment
        for payment_vals in self.get_payments_vals():
            payments += Payment.create(payment_vals)
        #===================================================================
        # ADD PAYMENT LINE
        #===================================================================
        for payment in payments:
            for line in self._get_register_lines(self.register_ids):
                self.env['account.payment.line'].create(self.get_payment_line_vals(payment, line))
        #===================================================================
        payments.post_multi()
        return {
            'name': _('Payments'),
            'domain': [('id', 'in', payments.ids), ('state', '=', 'posted')],
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.payment',
            'view_id': False,
            'type': 'ir.actions.act_window',
        }
    
#     #@api.multi
#     def create_payment(self):
#         payment = self.env['account.payment'].create(self.get_payment_vals())
#         if payment:
#             for line in self._get_register_lines(self.register_ids):
#                 self.env['account.payment.line'].create(self.get_payment_line_vals(payment, line))
#             payment.write({'register_date': self.payment_date, 
#                            'is_force_curr': self.is_force_curr, 
#                            'force_rate': self.force_rate,
#                            'payment_adm': self.payment_adm,
#                            'card_number': self.card_number,
#                            'card_type': self.card_type,
#                            })
#         payment.post_multi()
#         return payment#{'type': 'ir.actions.act_window_close'}
    
#     #@api.multi
#     def get_payments_vals(self):
#         '''Compute the values for payments.
# 
#         :return: a list of payment values (dictionary).
#         '''
#         if self.multi:
#             groups = self._groupby_invoices()
#             return [self._prepare_payment_vals(invoices) for invoices in groups.values()]
#         return [self._prepare_payment_vals(self.invoice_ids)]
#     
#     #@api.multi
#     def create_payments(self):
#         '''Create payments according to the invoices.
#         Having invoices with different commercial_partner_id or different type (Vendor bills with customer invoices)
#         leads to multiple payments.
#         In case of all the invoices are related to the same commercial_partner_id and have the same type,
#         only one payment will be created.
# 
#         :return: The ir.actions.act_window to show created payments.
#         '''
#         Payment = self.env['account.payment']
#         payments = Payment
#         for payment_vals in self.get_payments_vals():
#             payments += Payment.create(payment_vals)
#         payments.post()
# 
#         action_vals = {
#             'name': _('Payments'),
#             'domain': [('id', 'in', payments.ids), ('state', '=', 'posted')],
#             'view_type': 'form',
#             'res_model': 'account.payment',
#             'view_id': False,
#             'type': 'ir.actions.act_window',
#         }
#         if len(payments) == 1:
#             action_vals.update({'res_id': payments[0].id, 'view_mode': 'form'})
#         else:
#             action_vals['view_mode'] = 'tree,form'
#         return action_vals
    
class account_register_line(models.TransientModel):
    _name = 'account.register.line'
    _description = 'Account Line Register'

#     def _compute_total_invoices_amount(self):
#         """ Compute the sum of the residual of invoices, expressed in the payment currency """
#         payment_currency = self.currency_id or self.register_id.journal_id.currency_id or self.register_id.journal_id.company_id.currency_id or self.env.user.company_id.currency_id
#         if self.invoice_id.company_currency_id != payment_currency:
#             total = self.invoice_id.company_currency_id.with_context(date=self.register_id.payment_date).compute(self.invoice_id.residual_company_signed, payment_currency)
#         else:
#             total = self.invoice_id.residual_company_signed
#         return abs(total)
#     
#     @api.one
#     @api.depends('invoice_id', 'amount_to_pay', 'register_id.payment_date', 'currency_id')
#     def _compute_payment_difference(self):
#         if self.invoice_id.type in ['in_invoice', 'out_refund']:
#             self.payment_difference = self.amount_to_pay - self._compute_total_invoices_amount()
#         else:
#             self.payment_difference = self._compute_total_invoices_amount() - self.amount_to_pay
        
    #@api.one
    @api.depends('invoice_id', 'amount_total', 'residual', 'amount_to_pay', 'register_id.payment_date'
                 ,'currency_id'
                 )
    def _compute_payment_difference(self):
        self.payment_difference = self.residual - self.amount_to_pay
        
    register_id = fields.Many2one('account.payment.register', string='Register Payment')
    name = fields.Char(string='Description', required=True)
    invoice_id = fields.Many2one('account.move', string='Invoice')
    currency_invoice_id = fields.Many2one('res.currency', related='invoice_id.currency_id', string='Currency')
    amount_total = fields.Monetary('Amount Invoice', required=True, digits='Account')
    residual = fields.Monetary('Balance Invoice', required=True, digits='Account')
    currency_id = fields.Many2one('res.currency',  string='Currency')  
    to_reconcile = fields.Boolean('To Pay')
    amount_to_pay = fields.Monetary('Allocation', required=True, digits='Account')
    action = fields.Boolean('Action')
    payment_difference = fields.Monetary(compute='_compute_payment_difference', string='Payment Difference', readonly=True)
    payment_difference_handling = fields.Selection([('open', 'Keep open'), ('reconcile', 'Mark invoice as fully paid')], default='open', string="Write-off", copy=False)
    writeoff_account_id = fields.Many2one('account.account', string="Write-off Account", domain=[('deprecated', '=', False)], copy=False)
    
    @api.onchange('action')
    def _onchange_action(self):
        if not self.action:
            return
        self.amount_to_pay = self.action and self.residual or 0.0
    