# -*- coding: utf-8 -*-
import os.path
from jsonpointer import resolve_pointer
from copy import deepcopy
from openprocurement.historical.core.utils import (
    parse_hash,
    _apply_patch
)
from openprocurement.historical.core.constants import (
    VERSION,
    PREVIOUS_HASH as PHASH,
    HASH,
)
from base import test_tender_data, BaseTenderWebTest
from openprocurement.historical.core.tests.tests import (
    mock_doc
)


test_data_with_revisions = deepcopy(mock_doc)
test_data_with_revisions['doc_type'] = 'Tender'


class HistoricalTenderTestCase(BaseTenderWebTest):
    relative_to = os.path.dirname(__file__)

    def setUp(self):
        super(HistoricalTenderTestCase, self).setUp()

        self.app.authorization = ('Basic', ('broker', ''))

    def _update_doc(self):
        data = test_data_with_revisions.copy()
        tender = self.db.get(self.tender_id)
        data['_id'] = self.tender_id
        data['id'] = self.tender_id
        data['_rev'] = tender['_rev']
        self.db.save(data)

    def test_get_tender(self):
        response = self.app.get('/tenders')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(len(response.json['data']), 0)

        response = self.app.post_json('/tenders', {'data': test_tender_data})
        self.assertEqual(response.status, '201 Created')
        tender = response.json['data']
        response = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data'], tender)

        response = self.app.get('/tenders/{}/historical?opt_jsonp'
                                '=callback'.format(tender['id']))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/javascript')
        self.assertIn('callback({"data": {"', response.body)

        response = self.app.get('/tenders/{}/historical?'
                                'opt_pretty=1'.format(tender['id']))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertIn('{\n    "data": {\n        "', response.body)
        self.assertIn(VERSION, response.headers)
        self.assertEqual(response.headers[VERSION], '1')

        # test administrator view
        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data'], tender)

        # test forbidden
        self.app.authorization = ('Basic', ('', ''))
        response = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.json['data'], tender)

        response = self.app.get('/tenders/{}/historical'.format(tender['id']), status=403)
        self.assertEqual(response.status, '403 Forbidden')

    def test_get_tender_invalid_header(self):
        for header in ['invalid', '1.5', '-1', '10000', '0']:
            response = self.app.get('/tenders/{}/historical'.format(
                self.tender_id), headers={VERSION: header}, status=404)
            self.assertEqual(response.status, '404 Not Found')
            self.assertEqual(response.json['status'], 'error')
            self.assertEqual(response.json['errors'], [{
                u'description': u'Not Found',
                u'location': u'header',
                u'name': u'version'}]
            )

    def test_get_tender_versioned(self):
        response = self.app.get('/tenders')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(len(response.json['data']), 0)

        response = self.app.post_json('/tenders', {'data': test_tender_data})
        self.assertEqual(response.status, '201 Created')
        tender = response.json['data']
        self.tender_id = tender['id']
        self._update_doc()
        doc = test_data_with_revisions.copy()
        revisions = doc.pop('revisions')
        for i, rev in list(enumerate(revisions))[1:]:
            path = '/tenders/{}/historical'.format(self.tender_id)
            response = self.app.get(path, headers={VERSION: str(i)})
            tender = response.json['data']
            headers = response.headers
            self.assertEqual(headers[HASH], parse_hash(rev['rev']))
            self.assertEqual(headers[VERSION], str(i))
            self.assertEqual(headers[PHASH],
                             parse_hash(revisions[i-1].get('rev', '')))
            for ch in [r for r in rev['changes']]:
                val = ch['value'] if ch['op'] != 'remove' else 'missing'
                if not all(p for p in
                           ['next_check', 'shouldStartAfter']
                           if ch['path'] in p):
                    self.assertEqual(
                        resolve_pointer(tender, ch['path'], 'missing'), val)
                if not any('bids' in c['path'] for c in rev['changes']):
                    self.assertEqual(tender['dateModified'], rev['date'])
                else:
                    self.assertNotEqual(tender['dateModified'], rev['date'])

    def test_doc_type_mismatch(self):
        import pdb; pdb.set_trace()
        doc = self.db.get(self.tender_id)
        doc['doc_type'] = 'invalid'
        self.db.save(doc)
        response = self.app.get('/tenders/{}/historical'.format(
            self.tender_id), status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [{
            u'description': u'Not Found',
            u'location': u'url',
            u'name': u'tender_id'
        }])

    def test_get_doc_invalid_hash(self):
        self._update_doc()
        response = self.app.get('/tenders/{}/historical'.format(
            self.tender_id), headers={VERSION: str(3)})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        response = self.app.get('/tenders/{}/historical'.format(
            self.tender_id
        ), headers={VERSION: str(3), HASH: 'invalid'}, status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.json['status'], 'error')
        self.assertEqual(response.json['errors'], [{
            u'description': u'Not Found',
            u'location': u'header',
            u'name': u'hash'
        }])

    def test_get_tender_equal_with_api(self):
        data = test_data_with_revisions.copy()
        revisions = data.pop('revisions')
        tenders = []
        for p in reversed(revisions):
            data = _apply_patch(data, p['changes'])
            tenders.append(data.copy())

        for tender in reversed(tenders[:-1]):
            db_tender = self.db.get(self.tender_id)
            tender['id'] = tender['_id'] = db_tender['_id']
            tender['_rev'] = db_tender['_rev']

            self.db.save(tender)
            response = self.app.get('/tenders/{}/historical'.format(self.tender_id))
            historical_tender = response.json['data']
            response = self.app.get('/tenders/{}'.format(self.tender_id))
            tender = response.json['data']
            self.assertEqual(historical_tender, tender)

    def test_route_not_find(self):
        self.app.app.routes_mapper.routelist = [
            r for r in self.app.app.routes_mapper.routelist
            if r.name != 'Tender'
        ]
        response = self.app.get('/tenders/{}/historical'.format(self.tender_id), status=404)
        self.assertEqual(response.status, '404 Not Found')
        self.assertEqual(response.json['errors'], [
            {u'description': u'Not Found', u'location': u'url', u'name': u'tender_id'}
        ])

    def test_json_patch_error(self):
        self._update_doc()
        db_tender = self.db.get(self.tender_id)
        for rev in db_tender['revisions']:
            rev['changes'] = [{
                "path": "/skjddkfjsdkjfdsjk",
                "op": "remove"
            }]
        self.db.save(db_tender)

        resp = self.app.get('/tenders/{}/historical'.format(self.tender_id),
                            headers={VERSION: '11'},
                            status=501)
        self.assertEqual(resp.status, '501 Not Implemented')
        self.assertEqual(resp.json['status'], 'error')
        self.assertEqual(resp.json['errors'], [{
            u'description': u'Not Implemented',
            u'location': u'tender',
            u'name': u'revision'}
        ])


class TestGetHistoricalData(BaseTenderWebTest):
    relative_to = os.path.dirname(__file__)

    def setUp(self):
        super(TestGetHistoricalData, self).setUp()
        self.app.authorization = ('Basic', ('broker', ''))

    def _update_doc(self):
        data = test_tender_data.copy()
        tender = self.db.get(self.tender_id)
        data['_id'] = self.tender_id
        data['id'] = self.tender_id
        data['_rev'] = tender['_rev']
        self.db.save(data)

    def test_get_historical_data(self):
        response = self.app.get('/tenders')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(len(response.json['data']), 0)

        response = self.app.post_json('/tenders', {'data': test_tender_data})
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')

        tender = response.json['data']

        enquiries_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(enquiries_historical.status, '200 OK')
        self.assertEqual(enquiries_historical.content_type, 'application/json')
        enquiries = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(enquiries.status, '200 OK')
        self.assertEqual(enquiries.content_type, 'application/json')
        self.assertEqual(enquiries_historical.json['data'], enquiries.json['data'])

        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.set_status("active.tendering")

        tender = response.json['data']

        response = self.app.patch_json('/tenders/{}?acc_token={}'.format(
            tender['id'], self.tender_token), {"data": tender})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        self.app.authorization = ('Basic', ('broker', ''))

        tendering_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(tendering_historical.status, '200 OK')
        self.assertEqual(tendering_historical.content_type, 'application/json')
        tendering = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(tendering.status, '200 OK')
        self.assertEqual(tendering.content_type, 'application/json')
        self.assertEqual(tendering_historical.json['data'], tendering.json['data'])

        test_data1 = {
                  "data": {
                    "documents": [
                      {
                        "url": "http://public.docs-sandbox.openprocurement.org/get/331460f91e944a2d83136dee00b94f0f?KeyID=459f8ecf&Signature=TNOpuGEGleAHWS8gmR6mYc9O7e%2BEo2o28db4dVIaESJzcMyQVdTvA9xrfkzNXRGTlP2KUUpib8Bpk3rke2KkDg%3D%3D",
                        "title": "Proposal_part1.pdf",
                        "hash": "md5:00000000000000000000000000000000",
                        "format": "application/pdf"
                      },
                      {
                        "url": "http://public.docs-sandbox.openprocurement.org/get/3bfc49d63bd44e9488e1270003e52178?KeyID=459f8ecf&Signature=JXeIpHZQQo57b67ncruZEOHjEFrAtoW3GHrmDN4U2vOySIRAS9Hr5VrFh8BDZyhaYsiXjfqcCFWnxCxcPzdpBw%3D%3D",
                        "title": "Proposal_part2.pdf",
                        "hash": "md5:00000000000000000000000000000000",
                        "format": "application/pdf"
                      }
                    ],
                    "value": {
                      "amount": 499
                    },
                    "tenderers": [
                      {
                        "contactPoint": {
                          "telephone": "+380 (322) 91-69-30",
                          "name": u"Андрій Олексюк",
                          "email": "aagt@gmail.com"
                        },
                        "identifier": {
                          "scheme": "UA-EDR",
                          "id": "00137226",
                          "uri": "http://www.sc.gov.ua/"
                        },
                        "name": u"ДКП «Книга»",
                        "address": {
                          "countryName": u"Україна",
                          "postalCode": u"79013",
                          "region": u"м. Львів",
                          "streetAddress": u"вул. Островського, 34",
                          "locality": u"м. Львів"
                        }
                      }
                    ]
                  }
                }

        response = self.app.post_json('/tenders/{}/bids'.format(
            tender['id']), test_data1)
        self.assertEqual(response.status, '201 Created')
        self.assertEqual(response.content_type, 'application/json')

        tendering_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(tendering_historical.status, '200 OK')
        self.assertEqual(tendering_historical.content_type, 'application/json')
        tendering = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(tendering.status, '200 OK')
        self.assertEqual(tendering.content_type, 'application/json')
        self.assertEqual(tendering_historical.json['data'], tendering.json['data'])

        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.set_status("active.auction")

        tender = response.json['data']

        response = self.app.patch_json('/tenders/{}?acc_token={}'.format(
            tender['id'], self.tender_token), {"data": tender})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        self.app.authorization = ('Basic', ('broker', ''))

        auction_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(auction_historical.status, '200 OK')
        self.assertEqual(auction_historical.content_type, 'application/json')

        auction = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(auction.status, '200 OK')
        self.assertEqual(auction.content_type, 'application/json')
        self.assertEqual(auction_historical.json['data'], auction.json['data'])

        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.set_status("active.qualification")

        tender = response.json['data']

        response = self.app.patch_json('/tenders/{}?acc_token={}'.format(
            tender['id'], self.tender_token), {"data": tender})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        self.app.authorization = ('Basic', ('broker', ''))

        qualification_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(qualification_historical.status, '200 OK')
        self.assertEqual(qualification_historical.content_type, 'application/json')

        qualification = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(qualification.status, '200 OK')
        self.assertEqual(qualification.content_type, 'application/json')
        self.assertEqual(qualification_historical.json['data'], qualification.json['data'])
        self.assertEqual(qualification_historical.json['data']['bids'],
                         qualification.json['data']['bids'])

        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.set_status("active.awarded")

        tender = response.json['data']

        response = self.app.patch_json('/tenders/{}?acc_token={}'.format(
            tender['id'], self.tender_token), {"data": tender})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        self.app.authorization = ('Basic', ('broker', ''))

        awarded_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(awarded_historical.status, '200 OK')
        self.assertEqual(awarded_historical.content_type, 'application/json')

        awarded = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(awarded.status, '200 OK')
        self.assertEqual(awarded.content_type, 'application/json')
        self.assertEqual(awarded_historical.json['data'], awarded.json['data'])
        self.assertEqual(awarded_historical.json['data']['bids'],
                         awarded.json['data']['bids'])

        self.app.authorization = ('Basic', ('administrator', ''))
        response = self.set_status("complete")

        tender = response.json['data']

        response = self.app.patch_json('/tenders/{}?acc_token={}'.format(
            tender['id'], self.tender_token), {"data": tender})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')

        self.app.authorization = ('Basic', ('broker', ''))

        complete_historical = self.app.get('/tenders/{}/historical'.format(tender['id']))
        self.assertEqual(complete_historical.status, '200 OK')
        self.assertEqual(complete_historical.content_type, 'application/json')

        complete = self.app.get('/tenders/{}'.format(tender['id']))
        self.assertEqual(complete.status, '200 OK')
        self.assertEqual(complete.content_type, 'application/json')
        self.assertEqual(complete_historical.json['data'], complete.json['data'])
        self.assertEqual(complete_historical.json['data']['bids'],
                         complete.json['data']['bids'])