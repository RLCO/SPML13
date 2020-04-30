from odoo import models, fields, api,_
from odoo.exceptions import AccessError, UserError
from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

class BankAccount(models.Model):
    _inherit = 'account.bank.statement.line'

    bank_account = fields.Many2one('account.account', 'Account')
    employee_name = fields.Many2one('hr.employee', 'Employee')


class Manufactoring(models.Model):
    _inherit = 'mrp.production'

    extra_costs = fields.One2many('extra.cost', 'raw_material_extra')

class ExtraCosts(models.Model):
    _name = 'extra.cost'

    raw_material_extra = fields.Many2one('mrp.production', string='Name')
    name_extra = fields.Char(string='Name')
    cost_extra = fields.Float(string='Extra Cost')

class MrpCostStructure(models.AbstractModel):
    _inherit = 'report.mrp_account_enterprise.mrp_cost_structure'
    _description = 'MRP Cost Structure Report'

    def get_lines(self, productions):
        ProductProduct = self.env['product.product']
        StockMove = self.env['stock.move']


        res = []
        docs = []
        extra_cost = 0.0

        cost=[]

        print("production",productions)
        for product in productions.mapped('product_id'):
            mos = productions.filtered(lambda m: m.product_id == product)
            print("product",product)
            total_cost = 0.0
            mrpproduct = self.env['mrp.production'].search([('id', '=', mos.id)])
            # print(mrpproduct.name)
            total_cost = 0.0
            for i in mrpproduct.extra_costs:
                extra_cost = extra_cost + i.cost_extra
                docs.append({
                    'name_extra': i.name_extra,
                    'cost_extra': i.cost_extra,
                })


            #get the cost of operations
            operations = []
            Workorders = self.env['mrp.workorder'].search([('production_id', 'in', mos.ids)])
            print("Workorders",Workorders)
            if Workorders:
                query_str = """SELECT w.operation_id, op.name, partner.name, sum(t.duration), wc.costs_hour
                                FROM mrp_workcenter_productivity t
                                LEFT JOIN mrp_workorder w ON (w.id = t.workorder_id)
                                LEFT JOIN mrp_workcenter wc ON (wc.id = t.workcenter_id )
                                LEFT JOIN res_users u ON (t.user_id = u.id)
                                LEFT JOIN res_partner partner ON (u.partner_id = partner.id)
                                LEFT JOIN mrp_routing_workcenter op ON (w.operation_id = op.id)
                                WHERE t.workorder_id IS NOT NULL AND t.workorder_id IN %s
                                GROUP BY w.operation_id, op.name, partner.name, t.user_id, wc.costs_hour
                                ORDER BY op.name, partner.name
                            """
                self.env.cr.execute(query_str, (tuple(Workorders.ids), ))
                for op_id, op_name, user, duration, cost_hour in self.env.cr.fetchall():
                    operations.append([user, op_id, op_name, duration / 60.0, cost_hour])

            #get the cost of raw material effectively used
            raw_material_moves = []
            query_str = """SELECT sm.product_id, sm.bom_line_id, abs(SUM(svl.quantity)), abs(SUM(svl.value))
                             FROM stock_move AS sm
                       INNER JOIN stock_valuation_layer AS svl ON svl.stock_move_id = sm.id
                            WHERE sm.raw_material_production_id in %s AND sm.state != 'cancel' AND sm.product_qty != 0 AND scrapped != 't'
                         GROUP BY sm.bom_line_id, sm.product_id"""
            self.env.cr.execute(query_str, (tuple(mos.ids), ))
            for product_id, bom_line_id, qty, cost in self.env.cr.fetchall():
                raw_material_moves.append({
                    'qty': qty,
                    'cost': cost,
                    'product_id': ProductProduct.browse(product_id),
                    'bom_line_id': bom_line_id
                })
                total_cost += cost

            #get the cost of scrapped materials
            scraps = StockMove.search([('production_id', 'in', mos.ids), ('scrapped', '=', True), ('state', '=', 'done')])
            uom = mos and mos[0].product_uom_id
            mo_qty = 0
            if not all(m.product_uom_id.id == uom.id for m in mos):
                uom = product.uom_id
                for m in mos:
                    qty = sum(m.move_finished_ids.filtered(lambda mo: mo.state != 'cancel' and mo.product_id == product).mapped('product_qty'))
                    if m.product_uom_id.id == uom.id:
                        mo_qty += qty
                    else:
                        mo_qty += m.product_uom_id._compute_quantity(qty, uom)
            else:
                for m in mos:
                    mo_qty += sum(m.move_finished_ids.filtered(lambda mo: mo.state != 'cancel' and mo.product_id == product).mapped('product_qty'))


            for m in mos:
                byproduct_moves = m.move_finished_ids.filtered(lambda mo: mo.state != 'cancel' and mo.product_id != product)

            res.append({
                'product': product,
                'mo_qty': mo_qty,
                'mo_uom': uom,
                'operations': operations,
                'currency': self.env.company.currency_id,
                'raw_material_moves': raw_material_moves,
                'total_cost': total_cost,
                'scraps': scraps,
                # 'name_extra': i.name_extra,
                'docs': docs,
                'mocount': len(mos),
                'byproduct_moves': byproduct_moves,
                'extra_cost': extra_cost

            })

            print(res)
        return res

    @api.model
    def _get_report_values(self, docids, data=None):
        productions = self.env['mrp.production']\
            .browse(docids)\
            .filtered(lambda p: p.state != 'cancel')
        res = None
        if all([production.state == 'done' for production in productions]):
            res = self.get_lines(productions)
        return {'lines': res}


class ProductTemplateCostStructure(models.AbstractModel):
    _inherit = 'report.mrp_account_enterprise.product_template_cost_structure'
    _description = 'Product Template Cost Structure Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        productions = self.env['mrp.production'].search([('product_id', 'in', docids), ('state', '=', 'done')])
        res = self.env['report.mrp_account_enterprise.mrp_cost_structure'].get_lines(productions)
        return {'lines': res}

class MRPMaterial(models.Model):

    _inherit = 'mrp.production'
    _description = 'MRP Raw Material'

    def _get_default_scrap_location_id(self):
        company_id = self.env.context.get('default_company_id') or self.env.company.id
        return self.env['stock.location'].search([('name', '=', 'QC/Scrap')], limit=1).id

    def _get_default_location_id(self):
        company_id = self.env.context.get('default_company_id') or self.env.company.id
        return self.env['stock.location'].search(
            [('name', '=', 'My Company: Scrap'), ('location_id.name', '=', 'Virtual Locations')], limit=1).id

    state = fields.Selection(selection_add=[('raw', 'Request Raw Material'),('qc', 'Failed/Scrap'),('transfer', 'QC Check')])
    src_location_id=fields.Many2one('stock.location', 'QC location',  default=_get_default_scrap_location_id,
        )

    scrap_location_id = fields.Many2one('stock.location', 'Scrap location',
                                                   default=_get_default_location_id)
    qc_boolean = fields.Boolean(default=False)

    def action_request(self):
        dropship_vals = []
        # print("HEllo")
        self.write({'state': 'raw'})
        for company in self:
            location_id = self.env['stock.location'].search([('usage', '=', 'production')],limit=1)
            # location_id = self.env['stock.location'].search([('location_id.name', '=', 'Virtual Locations')])

            src_location_id = self.env['stock.location'].search([('name', '=', 'Stock'),('usage', '=', 'internal'),('location_id.name', '=', 'WH')],limit=1)
            for i in src_location_id:
                print(i.location_id.name)

            # print("src_location_id.name",src_location_id.name)
            sequence = self.env['ir.sequence'].search([
                ('code', '=', 'stock.dropshipping')])
            dropship_picking_type = self.env['stock.picking.type'].search([
                ('name', '=', 'Request Raw Material')], limit=1)

            product_car = self.env['product.product'].search([
                ('id', '=', company.product_id.id)], limit=1)

            dropship_vals.append({
                'name': 'Request Raw Material',
                'warehouse_id':self.env.user.company_id.id,
                'sequence_id': sequence.id,
                'code': 'internal',
                'default_location_src_id': src_location_id.id,
                'default_location_dest_id': location_id.id,
                'sequence_code': 'RRM',

            })
            if not dropship_picking_type:
                print("Inside")


                self.env['stock.picking.type'].create(dropship_vals)
                dropship_picking_type = self.env['stock.picking.type'].search([
                    ('name', '=', 'Request Raw Material')], limit=1)
                picking = self.env['stock.picking'].create({
                    'location_id': src_location_id.id,
                    'location_dest_id': location_id.id,
                    'partner_id': self._uid,
                    'origin': self.origin,
                    'picking_type_id': dropship_picking_type.id,
                    'immediate_transfer': True,

                })
                print(picking)
                for i in company.move_raw_ids:
                    # print(i.product_id.name)

                    move_receipt_1 = self.env['stock.move'].create({
                        'name': i.name,
                        'product_id': i.product_id.id,
                        'product_uom_qty': i.product_qty,
                        'quantity_done': company.product_qty,
                        'product_uom': i.product_id.uom_id.id,
                        'picking_id': picking.id,
                        'picking_type_id': dropship_picking_type.id,
                        'location_id': src_location_id.id,
                        'location_dest_id': location_id.id,
                    })
                    picking.action_confirm()

            else:
                print("else")
                location_id = self.env['stock.location'].search([('usage', '=', 'production')],limit=1)
                # print(dropship_picking_type.name)
                picking = self.env['stock.picking'].create({
                    'location_id': src_location_id.id,
                    'location_dest_id': location_id.id,
                    'partner_id': self._uid,
                    'origin': self.origin,
                    'picking_type_id': dropship_picking_type.id,
                    'immediate_transfer': True,
                })
                for i in company.move_raw_ids:
                    # print(i.product_id.name)

                    move_receipt_1 = self.env['stock.move'].create({
                        'name': i.name,
                        'product_id': i.product_id.id,
                        'product_uom_qty': i.product_qty,
                        'quantity_done': company.product_qty,
                        'product_uom': i.product_id.uom_id.id,
                        'picking_id': picking.id,
                        'picking_type_id': dropship_picking_type.id,
                        'location_id': src_location_id.id,
                        'location_dest_id': location_id.id,
                    })
                    # print(move_receipt_1)
                    # move_line_paw = self.env['stock.move.line'].create({
                    #     'product_id': i.product_id.id,
                    #     'product_uom_id': i.product_id.uom_id.id,
                    #     'picking_id': picking.id,
                    #     'qty_done': company.product_qty,
                    #     'location_id': self.env.ref('stock.stock_location_suppliers').id,
                    #     'location_dest_id': self.env.ref('stock.stock_location_customers').id,
                    # })
                    # print('l',l)
                    picking.action_confirm()

    def button_qc_sample(self):
        self.ensure_one()
        # self.write({'state': 'qc'})
        # src_location_id = self.env['stock.location'].search([('name', '=', 'YourCompany: QC/Scrap'),('location_id.name', '=', 'Virtual Locations')], limit=1)
        print("src_location_id",self.src_location_id.name)
        self.qc_boolean = True


        return {
            'name': _('QC Sample'),
                'view_mode': 'form',
                'res_model': 'stock.scrap',
                'view_id': self.env.ref('stock.stock_scrap_form_view2').id,
                'type': 'ir.actions.act_window',
                'context': {'default_production_id': self.id,
                             'default_product_id': self.product_id.id,
                            'product_ids': (self.finished_move_line_ids.filtered(lambda x: x.state not in ('done', 'cancel'))).mapped(
                    'product_id').ids,
                            },
                'target': 'new',
            }

    def button_scrap(self):
        # self.ensure_one()
        self.qc_boolean = False
        print("scrap_location_id",self.scrap_location_id.name)
        print("::::::::::::::::::::::::::::",self.location_dest_id.name)
        return {
            'name': _('Scrap'),
            'view_mode': 'form',
            'res_model': 'stock.scrap',
            'view_id': self.env.ref('stock.stock_scrap_form_view2').id,
            'type': 'ir.actions.act_window',
            'context': {'default_production_id': self.id,
                         'default_product_id': self.product_id.id,
                        'product_ids': (self.finished_move_line_ids.filtered(lambda x: x.state not in ('done', 'cancel'))).mapped(
                'product_id').ids,
                        },
            'target': 'new',
        }


    def action_internal(self):
        values_to_create = []
        active_id = self.id
        print("active_id",active_id)
        self.write({'state': 'transfer'})

        for production in self:
            points = self.env['quality.point'].search([('title', '=', 'RRM Quality Points')],limit=1)
            if points:
                points = self.env['quality.point'].search([('title','=','RRM Quality Points')],limit=1)
                picking_type_id = self.env['stock.picking.type'].search([('sequence_code', '=', 'RRM')],limit=1)
                test_type_id = self.env['quality.point.test_type'].search([('name', '=', 'Pass - Fail')])
                team_id = self.env['quality.alert.team'].search([('name', '=', 'Main Quality Team')])
                name = self.name
                picking_id = self.env['stock.picking'].search([('origin', '=', self.origin)],limit=1)
                quality_check_data = {
                    'picking_id': picking_id.id,
                    'product_id': self.product_id.id,
                    'point_id': points.id,
                    'company_id': self.company_id.id,
                    'team_id': team_id.id,
                    'test_type_id': test_type_id.id,
                    'origin': self.origin,
                }
                k = self.env['quality.check'].create(quality_check_data)
            else:
                picking_type_id=self.env['stock.picking.type'].search([('sequence_code','=','RRM')],limit=1)
                test_type_id = self.env['quality.point.test_type'].search([('name','=','Pass - Fail')])

                l=self.env['quality.point'].create({
                    'product_id': self.product_id.id,
                    'product_tmpl_id': self.product_id.product_tmpl_id.id,
                    'title': "RRM Quality Points",
                    'picking_type_id': picking_type_id.id,
                    'test_type_id': test_type_id.id
                })

                team_id = self.env['quality.alert.team'].search([('name', '=', 'Main Quality Team')])

                name=self.name
                picking_id = self.env['stock.picking'].search([('origin', '=', self.origin)],limit=1)

                quality_check_data = {
                    'picking_id': picking_id.id,
                    'product_id': self.product_id.id,
                    'point_id':points.id,
                    'company_id': self.company_id.id,
                    'team_id': team_id.id,
                    'test_type_id': test_type_id.id,
                    'origin': self.origin,
                }
                k=self.env['quality.check'].create(quality_check_data)



    def action_pass(self):
        print("Hello")

        scrapobj = self.env['stock.scrap'].search(
            [('production_id', '=', self.id), ('product_id', '=', self.product_id.id)])

        location_id = self.env['stock.location'].search([('name', '=', 'Finished Good')], limit=1)
        src_location_id = self.env['stock.location'].search(
            [('name', '=', 'Stock'), ('usage', '=', 'internal'), ('location_id.name', '=', 'WH')], limit=1)

        total = 0
        for i in scrapobj:
            total = total + i.scrap_qty
        for company in self:
            self.write({'state': 'transfer'})
            picking = self.env['stock.picking'].create({
                'location_id': location_id.id,
                'location_dest_id': src_location_id.id,
                'picking_type_id': self.env.ref('stock.picking_type_internal').id,
                'origin': self.origin,
            })
            for i in company:
                move_receipt_1 = self.env['stock.move'].create({
                    'name': i.name,
                    'product_id': i.product_id.id,
                    'product_uom_qty': company.product_qty - total,
                    'quantity_done': company.product_qty - total,
                    'product_uom': i.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'picking_type_id': self.env.ref('stock.picking_type_internal').id,
                    'location_id': location_id.id,
                    'location_dest_id': src_location_id.id,
                })
                print(" move_receipt_1",move_receipt_1['product_uom_qty'])
                k=self.env['stock.move.line'].create({
                    'move_id': move_receipt_1.id,
                    'picking_id': move_receipt_1.picking_id.id,
                    'product_id': move_receipt_1.product_id.id,
                    'location_id': move_receipt_1.location_id.id,
                    'location_dest_id': move_receipt_1.location_dest_id.id,
                    'product_uom_qty': company.product_qty - total,
                    'product_uom_id':move_receipt_1.product_id.uom_id.id,
                    'qty_done': company.product_qty - total,
                })

            picking.action_confirm()

    def button_mark_done(self):
        # for order in self:
            # if any([(x.quality_state == 'none') for x in order.check_ids]):
            #     raise UserError(_('You still need to do the quality checks!'))
        return super(MRPMaterial, self).button_mark_done()


    def button_mark_done(self):
            sequence = self.env['quality.check'].search([('origin', '=', self.origin)], limit=1)
            print(sequence.origin)
            if sequence.quality_state in ['pass']:
                self.ensure_one()
                self.action_pass()
                self._check_company()
                for wo in self.workorder_ids:
                    if wo.time_ids.filtered(lambda x: (not x.date_end) and (x.loss_type in ('productive', 'performance'))):
                        raise UserError(_('Work order %s is still running') % wo.name)
                self._check_lots()

                self.post_inventory()
                # Moves without quantity done are not posted => set them as done instead of canceling. In
                # case the user edits the MO later on and sets some consumed quantity on those, we do not
                # want the move lines to be canceled.
                (self.move_raw_ids | self.move_finished_ids).filtered(lambda x: x.state not in ('done', 'cancel')).write({
                    'state': 'done',
                    'product_uom_qty': 0.0,
                })
                return self.write({'date_finished': fields.Datetime.now()})

            else:
                raise UserError(_("First process the quality check."))




    # def post_inventory(self):
    #     sequence = self.env['quality.check'].search([('origin', '=', self.origin)], limit=1)
    #     print(sequence.origin)
    #     self.action_pass()
    #     if sequence.quality_state in ['pass']:
    #         for order in self:
    #             moves_not_to_do = order.move_raw_ids.filtered(lambda x: x.state == 'done')
    #             moves_to_do = order.move_raw_ids.filtered(lambda x: x.state not in ('done', 'cancel'))
    #             print("moves_to_do",moves_to_do)
    #             for move in moves_to_do.filtered(lambda m: m.product_qty == 0.0 and m.quantity_done > 0):
    #                 move.product_uom_qty = move.quantity_done
    #                 print("move.product_uom_qty",move.product_uom_qty)
    #             # MRP do not merge move, catch the result of _action_done in order
    #             # to get extra moves.
    #             moves_to_do = moves_to_do._action_done()
    #             moves_to_do = order.move_raw_ids.filtered(lambda x: x.state == 'done') - moves_not_to_do
    #             order._cal_price(moves_to_do)
    #             moves_to_finish = order.move_finished_ids.filtered(lambda x: x.state not in ('done', 'cancel'))
    #             moves_to_finish = moves_to_finish._action_done()
    #             order.workorder_ids.mapped('raw_workorder_line_ids').unlink()
    #             order.workorder_ids.mapped('finished_workorder_line_ids').unlink()
    #             order.action_assign()
    #             consume_move_lines = moves_to_do.mapped('move_line_ids')
    #             for moveline in moves_to_finish.mapped('move_line_ids'):
    #                 if moveline.move_id.has_tracking != 'none' and moveline.product_id == order.product_id or moveline.lot_id in consume_move_lines.mapped('lot_produced_ids'):
    #                     if any([not ml.lot_produced_ids for ml in consume_move_lines]):
    #                         raise UserError(_('You can not consume without telling for which lot you consumed it'))
    #                     # Link all movelines in the consumed with same lot_produced_ids false or the correct lot_produced_ids
    #                     filtered_lines = consume_move_lines.filtered(lambda ml: moveline.lot_id in ml.lot_produced_ids)
    #                     moveline.write({'consume_line_ids': [(6, 0, [x for x in filtered_lines.ids])]})
    #                 else:
    #                     # Link with everything
    #                     moveline.write({'consume_line_ids': [(6, 0, [x for x in consume_move_lines.ids])]})
    #         return True
    #
    #     else:
    #
    #             raise UserError(_("First process the Quality Check."))



    def action_confirm(self):
        sequence = self.env['stock.picking'].search([
            ('origin', '=', self.origin)],limit=1)
        print(sequence.origin)

        if sequence.state in ['done']:
            self._check_company()
            for production in self:
                if not production.move_raw_ids:
                    raise UserError(_("Add some materials to consume before marking this MO as to do."))
                for move_raw in production.move_raw_ids:
                    move_raw.write({
                        'group_id': production.procurement_group_id.id,
                        'unit_factor': move_raw.product_uom_qty / production.product_qty,
                        'reference': production.name,  # set reference when MO name is different than 'New'
                    })
                production._generate_finished_moves()
                production.move_raw_ids._adjust_procure_method()
                (production.move_raw_ids | production.move_finished_ids)._action_confirm()
            return True
        else:
            raise UserError(_("Request for Raw Material is not Validated yet."))



class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    @api.onchange('company_id')
    def _onchange_company_id(self):
        res = super(StockScrap, self)._onchange_company_id()
        if self.env.context.get('active_model') == 'mrp.production':
            request_id = self.env.context.get('active_ids', False)

            m = self.env['mrp.production'].browse(request_id[0])
            if m.qc_boolean == True:
                self.location_id = m.location_dest_id.id
                self.scrap_location_id = m.src_location_id.id
            else:
                self.location_id = m.location_dest_id.id
                self.scrap_location_id = m.scrap_location_id.id

        else:
            if self.company_id:
                warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
                self.location_id = warehouse.lot_stock_id
                self.scrap_location_id = self.env['stock.location'].search([
                    ('scrap_location', '=', True),
                    ('company_id', 'in', [self.company_id.id, False]),
                ], limit=1)
            else:
                self.location_id = False
                self.scrap_location_id = False

        return res


    # location_id = fields.Many2one('stock.location', 'Source Location')
    # scrap_location_id = fields.Many2one('stock.location', 'Scrap Location')

class QualityCheck(models.Model):
    _inherit = "quality.check"

    origin=fields.Char("Source")

    def do_fail(self):
        res = super(QualityCheck, self).do_fail()
        mrpobj = self.env['mrp.production'].search([('origin', '=', self.origin)],limit=1)
        picking_id = self.env['stock.picking'].search([('origin', '=', self.origin)], limit=1)
        mrpobj.state='qc'
        mrpobj.action_see_move_scrap()
        print(mrpobj.picking_type_id.name)
        self.write({
            'quality_state': 'fail',
            'user_id': self.env.user.id,
            'control_date': datetime.now()})
        self.redirect_after_pass_fail()
        # picking.button_scrap()
        # scrap = self.env['stock.scrap'].create({
        #     'product_id': self.product_id.id,
        #     'product_uom_id': self.product_id.uom_id.id,
        #     'scrap_qty': mrpobj.product_qty,
        #     'origin': self.origin,
        #     'picking_id': picking_id.id,
        #     'state':'done'
        # })
        dropship_picking_type = self.env['stock.picking.type'].search([
            ('name', '=', 'Request Raw Material')], limit=1)
        picking = self.env['stock.picking'].create({
            'location_id': mrpobj.location_dest_id.id,
            'location_dest_id': mrpobj.src_location_id.id,
            'partner_id': self._uid,
            'origin': self.origin,
            'picking_type_id': dropship_picking_type.id,
            'immediate_transfer': True,

        })
        print(picking)
        for i in mrpobj.move_raw_ids:
            # print(i.product_id.name)

            move_receipt_1 = self.env['stock.move'].create({
                'name': i.name,
                'product_id': i.product_id.id,
                'product_uom_qty': i.product_qty,
                'quantity_done': mrpobj.product_qty,
                'product_uom': i.product_id.uom_id.id,
                'picking_id': picking.id,
                'picking_type_id': dropship_picking_type.id,
                'location_id': mrpobj.location_dest_id.id,
                'location_dest_id': mrpobj.src_location_id.id,
            })
            picking.action_confirm()
            picking.button_validate()
            picking.button_scrap()

            self.env['stock.move.line'].create({
                'move_id': move_receipt_1.id,
                # 'lot_id': move_line.lot_id.id,
                'qty_done': i.product_qty,
                'product_id': i.product_id.id,
                'product_uom_id': i.product_id.uom_id.id,
                'location_id': mrpobj.location_dest_id.id,
                'location_dest_id': mrpobj.src_location_id.id,
                'state': 'done',
            })

        # scrap.sudo().action_validate()
        return res


    def do_pass(self):

        mrpobj = self.env['mrp.production'].search([('origin', '=',self.origin)],limit=1)

        print("mrpobj",mrpobj.origin)



        self.write({'quality_state': 'pass',
                    'user_id': self.env.user.id,
                    'control_date': datetime.now()})
        mrpobj.button_mark_done()
        return self.redirect_after_pass_fail()

class StockPicking(models.Model):
    _inherit = "stock.picking"


    def check_quality(self):
        self.ensure_one()
        checks = self.check_ids.filtered(lambda check: check.quality_state == 'none')
        # if checks:
        #     action = self.env.ref('quality_control.quality_check_action_small').read()[0]
        #     action['context'] = self.env.context
        #     action['res_id'] = checks.ids[0]
        #     return action
        return False


    def action_done(self):
        # Do the check before transferring
        product_to_check = self.mapped('move_line_ids').filtered(lambda x: x.qty_done != 0).mapped('product_id')
        # if self.mapped('check_ids').filtered(lambda x: x.quality_state == 'none' and x.product_id in product_to_check):
        #     raise UserError(_('You still need to do the quality checks!'))
        return super(StockPicking, self).action_done()

class MrpProductionWorkcenterLine(models.Model):
    _inherit = 'mrp.workorder'



    def record_production(self):
        self.ensure_one()
        # if any([(x.quality_state == 'none') for x in self.check_ids]):
        #     raise UserError(_('You still need to do the quality checks!'))
        if (self.production_id.product_id.tracking != 'none') and not self.finished_lot_id and self.move_raw_ids:
            raise UserError(_('You should provide a lot for the final product'))
        if self.check_ids:
            # Check if you can attribute the lot to the checks
            if (self.production_id.product_id.tracking != 'none') and self.finished_lot_id:
                self.check_ids.filtered(lambda check: not check.finished_lot_id).write({
                    'finished_lot_id': self.finished_lot_id.id
                })
        res = super(MrpProductionWorkcenterLine, self).record_production()
        rounding = self.product_uom_id.rounding
        if float_compare(self.qty_producing, 0, precision_rounding=rounding) > 0:
            self._create_checks()
        return res
