from odoo import api, fields, models 
from datetime import datetime 

class AccountJournal(models.Model):
    _inherit = "account.journal"

    type = fields.Selection(selection_add=[
            ('sale_advance', 'Advance Sale'),
            ('purchase_advance', 'Advance Purchase')])
    
    
class AccountMove(models.Model):
    _inherit = "account.move"
    
    attn = fields.Char('Attention',size=64)
    signature = fields.Char('Signature', size=64)
    journal_bank_id = fields.Many2one('account.journal', string='Payment Method', domain=[('type', 'in', ('cash','bank'))])
    
class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
    def _get_price_tax(self):
        for l in self:
            l.price_tax = l.price_total - l.price_subtotal
            
    price_tax = fields.Monetary(string='Tax Amount', compute='_get_price_tax', currency_field='always_set_currency_id')
    
    @api.model
    def _get_price_total_and_subtotal_model(self, price_unit, quantity, discount, currency, product, partner, taxes, move_type):
        res = super(AccountMoveLine, self)._get_price_total_and_subtotal_model(price_unit=price_unit, quantity=quantity, discount=discount, currency=currency, product=product, partner=partner, taxes=taxes, move_type=move_type)
        if taxes:
            res['price_tax'] = res['price_total'] - res['price_subtotal']
        else:
            res['price_tax'] = 0.0
        return res
    