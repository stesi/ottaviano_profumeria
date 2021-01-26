from tempfile import TemporaryFile

from odoo import api, fields, models, _
import os, glob, datetime
import pytz
import base64
from odoo.exceptions import UserError, ValidationError
import xml.etree.ElementTree as XMLParser
from lxml import etree
import traceback, sys
import logging

_logger = logging.getLogger(__name__)


class ImportOrder(models.TransientModel):
    _name = "ottaviano.profumeria.import.order"
    _description = 'Import Order and OrderLine from XML'
    # file_data = fields.Binary('File')
    #
    # def action_check_wizard(self):
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'ottaviano.profumeria.import.order',
    #         'view_type': 'form',
    #         'view_mode': 'form',
    #         'views': [(self.env.ref('ottaviano_profumeria.ottaviano_profumeria_import_order').id, 'form')],
    #         'target': 'new',
    #         'context': {}
    #     }
    #
    # def action_import_file(self, cr, uid, ids, context=None):
    #     fileobj = TemporaryFile('w+')
    #     fileobj.write(base64.decodestring(self.file_data))
    #     self.importFromDirectoryXML(fileobj)
    #     # your treatment
    #     return

    @api.model
    def importFromDirectoryXML(self, filename, create_invoice=False):
        company_id = self.env.user.company_id.id

        xml = etree.parse(filename)
        root = xml.getroot()
        documentsHeader = root.find('Documents')
        documents = documentsHeader.findall('Document')
        customerTag = False
        i = 0
        print(str(len(documents)))
        for document in documents:
            try:
                i += 1
                print("Number document " + str(i) + " line " + str(document.sourceline))
                customerTag = document.find('CustomerCode')
                partner = False
                if customerTag is not None and customerTag.text:
                    partner_id = self.env['res.partner'].search([('ref', '=', customerTag.text)], limit=1)
                    if not partner_id.id:
                        partner_id = self.env['res.partner'].create({
                            'name': customerTag.text,
                            'company_id': self.env.user.company_id.id,
                            'ref': customerTag.text
                        })
                    partner = partner_id.id
                    # raise ValidationError("Partner " + customerTag.text + " not found for document " + str(i))

                warehouse = document.find('Warehouse')
                if warehouse is not None and warehouse.text:
                    # session_id
                    pos_config = self.env['pos.config'].search([('name', '=', warehouse.text)], limit=1)
                    if not pos_config.id:
                        raise ValidationError(
                            "Warehouse " + warehouse.text + " not found for document " + str(i) + ' sourceline ' + str(
                                document.sourceline))
                    if not pos_config.current_session_id:
                        raise ValidationError(
                            "Session not opened for warehouse " + warehouse.text + ' sourceline ' + str(
                                document.sourceline))
                    session = pos_config.current_session_id

                    date_tag = document.find('Date')
                    if date_tag is not None and date_tag.text:
                        date_order = datetime.datetime.strptime(date_tag.text, "%Y-%m-%d")
                    else:
                        raise ValidationError(
                            "Date section value not found for document " + str(i) + ' sourceline ' + str(
                                document.sourceline))

                    total = 0
                    total_without_tax = document.find('TotalWithoutTax')
                    if total_without_tax.text:
                        total += float(total_without_tax.text)
                    vat_amount = document.find('VatAmount')
                    amount_tax = 0
                    if vat_amount.text:
                        amount_tax = float(vat_amount.text)
                        total += float(vat_amount.text)

                    nb_print = False
                    number_tag = document.find('Number')
                    if number_tag.text:
                        nb_print = number_tag.text

                    order = self.env['pos.order'].create({
                        'name': nb_print,
                        'company_id': company_id,
                        'date_order': date_order,
                        'partner_id': partner,
                        'session_id': session.id,
                        'amount_total': total,
                        'amount_tax': amount_tax,
                        'amount_paid': 0,
                        'amount_return': 0,
                        'nb_print': nb_print
                    })

                    rowsHeader = document.find('Rows')
                    rows = rowsHeader.findall('Row')
                    j = 0
                    for row in rows:
                        j += 1
                        code = row.find('Code')
                        product_text = code.text
                        if not product_text:
                            product_text = 'Info'
                        product_id = self.env['product.product'].search([('default_code', '=', product_text)], limit=1)
                        if not product_id.id:
                            product_category_id = self.env['product.category'].search([('name','=','Imported')],limit=1)
                            if not product_category_id:
                                product_category_id = self.env['product.category'].create({
                                    'name': 'Imported',
                                })

                            product_id = self.env['product.product'].create(
                                {'name': product_text, 'default_code': product_text,
                                 'categ_id':product_category_id.id,
                                 'company_id': self.env.user.company_id.id, })
                            # _logger.warning(
                            #     "Product section value not found for document " + str(i) + " row " + str(j)+ ' sourceline ' + str(document.sourceline))
                            # continue

                        name = False
                        description = row.find('Description')
                        if description.text:
                            name = description.text

                        quantity = 0
                        quantityTag = row.find('Qty')
                        if quantityTag.text:
                            quantity = float(quantityTag.text)

                        price = 0
                        priceTag = row.find('Price')
                        if priceTag.text:
                            price = float(priceTag.text)
                        account_tax = False
                        subtotal = 0
                        vatTag = row.find('VatCode')
                        vat=False
                        if vatTag.text:
                            vat = float(vatTag.text)
                            account_tax = self.env['account.tax'].search([('amount','=',vat),
                                                                          ('type_tax_use','=','sale')],limit=1)


                        subtotal = 0
                        total = 0
                        totalTag = row.find('Total')
                        if totalTag.text:
                            total = float(totalTag.text)
                            if vat > 0:
                                subtotal = round((total*100) / (100+vat),2)

                        discount = False
                        discountTag = row.find('Discounts')

                        if discountTag.text:
                            discount = discountTag.text.replace("%", "")
                            total_temp = price
                            if '+' in discount:
                                pair_list = discount.split("+")
                                discount_temp = 0
                                for disc in pair_list:
                                    discount_temp = (total_temp * float(disc) / 100) + discount_temp
                                    total_temp = total_temp - discount_temp
                                discount = discount_temp
                            else:
                                discount = price * float(discount) / 100

                        line = self.env['pos.order.line'].create({
                            'product_id': product_id.id,
                            'price_unit': price,
                            'discount': discount,
                            'order_id': order.id,
                            'full_product_name': name,
                            'qty': quantity,
                            'price_subtotal': total - subtotal,
                            'price_subtotal_incl': total
                        })
                        if account_tax:
                            line.tax_ids |= account_tax

                    payment = False
                    paymentNameTag = document.find('PaymentName')
                    if paymentNameTag.text:
                        payment = paymentNameTag.text
                        if payment.lower() != 'contanti' and payment.lower() != 'contrassegno':
                            payment_method = self.env['pos.payment.method'].search([('name', '=', 'Bank')],
                                                                                   limit=1)
                        else:
                            payment_method = self.env['pos.payment.method'].search([('name', '=', 'Cash')],
                                                                                   limit=1)
                    else:
                        payment_method = self.env['pos.payment.method'].search([('name', '=', 'Cash')],
                                                                               limit=1)
                        payment = "Contanti"

                    posMakePayment = self.env['pos.make.payment']
                    # I make a payment to fully pay the order
                    context_make_payment = {"active_ids": [order.id],
                                                "active_id": order.id}
                    pos_make_payment_0 = posMakePayment.with_context(context_make_payment).create(
                            {
                                'amount': order.amount_total,
                                'payment_method_id': payment_method.id,
                                'payment_name': payment
                            })
                    # print(pos_make_payment_0.id)
                    # I click on the validate button to register the payment.
                    context_payment = {'active_id': order.id}
                    pos_make_payment_0.with_context(context_payment).check()
                    if create_invoice:
                        order.action_pos_order_invoice()
                else:
                    raise ValidationError(
                        "Warehouse section value not found for document " + str(i) + ' sourceline ' + str(
                            document.sourceline))

            except ValidationError as inst:
                _logger.warning(str(inst))
                print("Line " + str(document.sourceline) + str(inst))

            except Exception as inst:
                _logger.error(str(inst))
                print("Line " + str(document.sourceline) + str(inst))

# 'lines': [(0, 0, {
#     'name': "OL/0001",
#     'product_id': self.pos_product.id,
#     'price_unit': price_unit,
#     'qty': qty,
#     'tax_ids': [(6, 0, self.pos_tax.ids)],
#     'price_subtotal': qty * price_unit,
#     'price_subtotal_incl': rounded_total,
# })],
