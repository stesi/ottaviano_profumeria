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

    @api.model
    def importFromDirectoryXML(self, filename,create_invoice):
        company_id = self.env.user.company_id.id

        xml = etree.parse(filename)
        root = xml.getroot()
        documentsHeader = root.find('Documents')
        documents = documentsHeader.findall('Document')
        i = 0
        for document in documents:
            try:
                i += 1
                customerTag = document.find('CustomerCode')
                if customerTag.text:
                    partner_id = self.env['res.partner'].search([('ref', '=', customerTag.text)], limit=1)
                    if not partner_id.id:
                        raise ValidationError("Partner " + customerTag.text + " not found for document " + str(i))

                    warehouse = document.find('Warehouse')
                    if warehouse.text:
                        # session_id
                        pos_config = self.env['pos.config'].search([('name', '=', warehouse.text)], limit=1)
                        if not pos_config.id:
                            raise ValidationError("Warehouse " + warehouse.text + " not found for document " + str(i))
                        if not pos_config.current_session_id:
                            raise ValidationError("Session not opened for warehouse " + warehouse.text )
                        session = pos_config.current_session_id

                        date_tag = document.find('Date')
                        if date_tag.text:
                            date_order = datetime.datetime.strptime(date_tag.text, "%Y-%m-%d")
                        else:
                            raise ValidationError("Date section value not found for document " + str(i))


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
                            'name':nb_print,
                            'company_id': company_id,
                            'date_order' : date_order,
                            'partner_id': partner_id.id,
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
                            if code.text:
                                product_id = self.env['product.product'].search([('default_code', '=', code.text)], limit=1)
                                if not product_id.id:
                                    _logger.warning(
                                        "Product section value not found for document " + str(i) + " row " + str(j))
                                    continue

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



                                subtotal = 0
                                vatTag = row.find('VatCode')
                                if vatTag.text:
                                    vat = float(vatTag.text)

                                total = False
                                totalTag = row.find('Total')
                                if totalTag.text:
                                    total = float(totalTag.text)

                                subtotal = 0

                                if vat > 0:
                                    subtotal = (total * vat) / 100

                                discount = False
                                discountTag = row.find('Discounts')
                                if discountTag.text:
                                    discount = discountTag.text.replace("%", "")
                                    discount = total * 100 / float(discount)

                                line = self.env['pos.order.line'].create({
                                    'product_id': product_id.id,
                                    'price_unit': price,
                                    'discount': discount,
                                    'order_id': order.id,
                                    'full_product_name':name,
                                    'qty': quantity,
                                    'price_subtotal': total - subtotal,
                                    'price_subtotal_incl': total,
                                })




                            else:
                                _logger.warning("Product section value not found for document " + str(i) + " row " + str(j))

                            payment = False
                            paymentNameTag = document.find('PaymentName')
                            if paymentNameTag.text:
                                payment = paymentNameTag.text
                                if 'Contanti' not in payment and 'Banc' in payment:
                                    payment_method = self.env['pos.payment.method'].search([('name', '=', 'Bank')],
                                                                                               limit=1)
                                else:
                                    payment_method = self.env['pos.payment.method'].search([('name', '=', 'Cash')],
                                                                                               limit=1)
                                posMakePayment = self.env['pos.make.payment']
                                # I make a payment to fully pay the order
                                context_make_payment = {"active_ids": [order.id],
                                                        "active_id": order.id}
                                pos_make_payment_0 = posMakePayment.with_context(context_make_payment).create(
                                    {
                                        'amount': total,
                                        'payment_method_id': payment_method.id,
                                        'payment_name':payment
                                    })
                                print(pos_make_payment_0.id)
                                # I click on the validate button to register the payment.
                                context_payment = {'active_id': order.id}
                                pos_make_payment_0.with_context(context_payment).check()

                                if create_invoice:
                                    order.action_pos_order_invoice()

                    else:
                        raise ValidationError("Warehouse section value not found for document " + str(i))
                else:
                    raise ValidationError("Customer section value not found for document " + str(i))

            except ValidationError as inst:
                _logger.warning(str(inst))

            except Exception as inst:
                _logger.error(str(inst))

                # 'lines': [(0, 0, {
                #     'name': "OL/0001",
                #     'product_id': self.pos_product.id,
                #     'price_unit': price_unit,
                #     'qty': qty,
                #     'tax_ids': [(6, 0, self.pos_tax.ids)],
                #     'price_subtotal': qty * price_unit,
                #     'price_subtotal_incl': rounded_total,
                # })],
