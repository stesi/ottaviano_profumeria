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
    def importFromDirectoryXML(self, filename):
        for order in self:
            company_id = self.env.user.company_id.id

            xml = etree.parse(filename)
            root = xml.getroot()
            documentsHeader = root.find('Documents')
            documents = documentsHeader.findall('Document')
            i = 0
            for document in documents:
                try:
                    i+=1
                    customerTag = document.find('CustomerCode')
                    if customerTag.text:
                        partner_id =  self.env['pos.config'].search([('ref', '=',customerTag.text)],limit = 1)
                        if not partner_id.id :
                            raise ValidationError("Partner " + customerTag.text + " not found for document " + str(i))

                        warehouse = document.find('Warehouse')
                        pos_config = False
                        if warehouse.text:
                            #session_id
                            session = self.env['pos.config'].search([('name', '=',warehouse.text)],limit = 1)
                            if not pos_config.id:
                                raise ValidationError("Warehouse " +warehouse.text+ " not found for document " + str(i))
                            date_tag = document.find('Date')
                            if date_tag.text:
                                date_order = datetime.datetime.strptime(date_tag.text, '%Y%m%d%')
                            else:
                                raise ValidationError("Date section value not found for document " + str(i))

                            number_tag = document.find('Number')
                            if number_tag.text:
                                nb_print = number_tag.text
                            else:
                                raise ValidationError("Date section value not found for document " + str(i))

                            total =  0
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
                                'company_id': company_id,
                                'partner_id': partner_id.id,
                                'session_id': session.id,
                                'amount_total': total,
                                'amount_tax': amount_tax,
                                'amount_paid': 0,
                                'amount_return': 0,
                                'nb_print':nb_print
                            })

                            rowsHeader = root.find('Rows')
                            rows = rowsHeader.findall('Row')
                            j=0
                            for row in rows:
                                j+=1
                                product_id = row.find('Code')
                                if product_id.text:
                                    product = self.env['product.product'].search([('code','=',product_id.text)],limit=1)
                                    if not product_id.id:
                                        _logger.warning("Product section value not found for document " + str(i) + " row " + j)
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

                                    discount = False
                                    discountTag = row.find('Discount')
                                    if discountTag.text:
                                        discount = float(discountTag.text)

                                    subtotal = 0
                                    vatTag = row.find('VatCode')
                                    if vatTag.text:
                                        vat = float(vatTag.text)


                                    total = False
                                    totalTag = row.find('Total')
                                    if totalTag.text:
                                        total = float(totalTag.text)

                                    subtotal = 0

                                    if vat>0:
                                        subtotal = (total * vat)/100

                                    line = self.env['pos.order.line'].create({
                                            'name': description,
                                            'product_id': product_id.id,
                                            'price_unit': price,
                                            'discount':discount,
                                            'order_id':order.id,
                                            'qty': quantity,
                                            'price_subtotal': subtotal,
                                            'price_subtotal_incl': total,
                                        })

                                else:
                                   _logger.warning("Product section value not found for document " + str(i) + " row " +j)

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






