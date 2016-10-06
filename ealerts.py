#!/usr/bin/env python
''' Schedule using cron
# 0-Sun, 6-Sat
10-59/5 23 * * 0-5 script
# optional
*/5 0 * * 0-5 script
'''
import requests
import sys, traceback, time
import smtplib
from email.mime.text import MIMEText
from boto.dynamodb2.layer1 import DynamoDBConnection
from boto.dynamodb2.fields import HashKey
from boto.dynamodb2.table import Table
from boto.regioninfo import RegionInfo
DEBUG = False
USELOCALDB = False
ALERT = 'Alert'
DBTABLE = 'EAlerts'
MTIME = 'mtime'
ALERTED = 'alerted'
COUNT = 'count'
if DEBUG:
    ALERT = 'Test'
    import logging

    # These two lines enable debugging at httplib level
    # (requests->urllib3->http.client)
    # You will see the REQUEST, including HEADERS and MTIME, and RESPONSE
    # with HEADERS but without MTIME.
    # The only thing missing will be the response.body which is not logged.
    try:
        import http.client as http_client
    except ImportError:
        # Python 2
        import httplib as http_client
    http_client.HTTPConnection.debuglevel = 1

    # You must initialize logging, otherwise you'll not see DEBUG output.
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    log1 = logging.getLogger('requests.packages.urllib3')
    log1.setLevel(logging.DEBUG)
    log1.propagate = True

class EmailClient(object):

    def __init__(self, smtp_server, smtp_port, email, password):
        self.email = email
        self.password = password
        self.server = smtp_server
        self.port = smtp_port
        session = smtplib.SMTP(self.server, self.port)
        session.ehlo()
        session.starttls()
        session.login(self.email, self.password)
        self.session = session

    def send_message(self, email_from, email_to, subject, body):
        messg = MIMEText(body, 'plain')
        messg['From'] = email_from
        messg['To'] = ', '.join(email_to)
        messg['Subject'] = subject
        msg = messg.as_string()
        if DEBUG:
            print ">>>{}<<<".format(msg)
        self.session.sendmail(email_from, email_to, msg)

    def close(self):
        self.session.close()


class ElectricCarChargeAlert(object):

    def __init__(self):
        self.hr1 = 7200
        # how many time power below the set threshold before sending email
        self.th1 = 2
        # expected power consumption rate, kwh, when car is charged
        self.pc1 = 1.5
        self.url1 = 'https://rainforestcloud.com:9445/cgi-bin/post_manager'
        self.request_xml1 = \
        '''
            <Command>
              <Name>get_instantaneous_demand</Name>
              <Format>JSON</Format>
            </Command>
        '''

    def handler(self, event, context):
        alert_type = event['alert_type']
        eagle_username = event['eagle_username']
        eagle_password = event['eagle_password']
        eagle_cloud_id = event['eagle_cloud_id']
        smtp_server = event['smtp_server']
        smtp_port = event['smtp_port']
        smtp_email_from = event['smtp_email_from']
        smtp_username = event['aws_ses_access_key_id']
        smtp_password = event['aws_ses_secret_access_key']
        smtp_email_to_list = event['smtp_email_to_list']
        aws_db_access_key_id = event['aws_db_access_key_id']
        aws_db_secret_access_key = event['aws_db_secret_access_key']
        headers = {
            'Accept': '*/*',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'Content-Type': 'text/xml',
            'Cloud-ID': eagle_cloud_id,
            'User': eagle_username,
            'Password': eagle_password
        }

        try:
            response = requests.post(self.url1, data=self.request_xml1,
                                     headers=headers, allow_redirects=False,
                                     verify=True)
        except requests.RequestException as e:
            print 'Connection failure: {0}\nExiting..'.format(e)
            die(event, e)

        if response.status_code != requests.codes.OK:
            print 'Request failure: Status {0}\nText {1}\nExiting..'.format(
                response.status_code, response.text)
            die(event)

        response_json = response.json()

        try:
            # begin db_item ensure db_item exists
            db_table = event[DBTABLE]
            db_item = None
            if db_table.query_count(alert_type__eq=alert_type) > 0:
                db_item = db_table.lookup(alert_type)
            if db_item is None:
                db_table.put_item(data={'alert_type':alert_type},
                                  overwrite=True)
                db_item = db_table.lookup(alert_type)
            # end db_item

            demand = float(int(response_json['InstantaneousDemand']['Demand'],
                               0))
            demand_kwh = demand/1000
            print '{}kwh'.format(demand_kwh)
            # To ensure we r talking to a live meter use a threshold with
            # demand > 0.1kw. demand > 1.0kW between 11:30pm to 4:00am
            if demand_kwh > 0.1:
                uts = int(time.time())
                if demand_kwh < self.pc1:
                    if not db_item.get(ALERTED):
                        c1 = 1
                        if db_item.get(MTIME):
                            # catch exception to take care of corrupted file
                            # or file with invalid content
                            try:
                                mtime = int(db_item[MTIME])
                                if (uts - mtime) < self.hr1:
                                    c1 = int(db_item[COUNT])
                                    c1 += 1
                                    if c1 >= self.th1:
                                        print 'BEGIN:: Sending sms at time {}'\
                                            'to '\
                                            '{}'.format(uts, smtp_email_to_list)
                                        # send sms and delete file
                                        ec1 = EmailClient(smtp_server,
                                                          smtp_port,
                                                          smtp_username,
                                                          smtp_password)
                                        ec1.send_message(smtp_email_from,
                                                         smtp_email_to_list,
                                                         '{}: Check Electric'
                                                         ' Car'.format(ALERT),
                                                         'Power Consume'
                                                         'd is {}kwh'
                                                         .format(demand_kwh))
                                        ec1.close()
                                        print 'DONE:: Sending sms'
                                        c1 = 1
                                        # set an alerted flag to avoid
                                        # sending multiple alerts.
                                        # when this script detects a normal
                                        # charging level the flag is
                                        # deleted (see below)
                                        db_item[ALERTED] = True
                            except Exception, ex1:
                                print ex1
                        db_item[MTIME] = uts
                        db_item[COUNT] = c1
                        db_item.save()
                    else:
                        # if alerted flag is older than hr1 remove it
                        mtime = int(db_item[MTIME])
                        if DEBUG:
                            print '(uts {} - mtime {}) > self.hr1 {}'\
                                  .format(uts, mtime, self.hr1)
                        if (uts - mtime) > self.hr1:
                            del db_item[ALERTED]
                            db_item[COUNT] = 0
                            db_item[MTIME] = uts
                            db_item.save()
                            print 'removed old alerted flag created at {}!'\
                                  .format(mtime)
                        else:
                            print 'alerted flag exists, created at {} current'\
                                  ' time {}. skip!'.format(mtime, uts)
                else:
                    # clear up alerted flag only if the power consumption is
                    # back to normal for the monitored hours --this logic
                    # ensures the sms alert is only sent out once if the car is
                    # purposely left unplugged for longer periods, e.g., if one
                    # goes off to a vacation
                    if db_item.get(ALERTED):
                        del db_item[ALERTED]
                        db_item[COUNT] = 0
                        db_item[MTIME] = uts
                        db_item.save()
        except Exception, ex2:
            print ex2
            print >> sys.stderr, traceback.print_exc()
            print >> sys.stderr, '\n'
            traceback.print_stack(file=sys.stderr)
            sys.stderr.flush()
            die(event, ex2)
        return '{}kwh'.format(demand_kwh)

class TrafficAlert(object):

    def __init__(self):
        self.hr1 = 7200
        # how many time traffic above the set threshold before sending email
        self.th1 = 2
        # normal journey time when no traffic
        self.url1 = 'https://maps.googleapis.com/maps/api/directions/json?'\
                    'origin={}&destination={}&departure_time={}&key={}'
        self.url2 = 'https://www.google.com/maps/dir/{}/{}'

    def handler(self, event, context):
        alert_type = event['alert_type']
        journey_origin = event['journey_origin']
        journey_destination = event['journey_destination']
        journey_delay_factor = event['journey_delay_factor']
        journey_reverse = event['journey_reverse']
        google_api_key = event['google_api_key']
        smtp_server = event['smtp_server']
        smtp_port = event['smtp_port']
        smtp_email_from = event['smtp_email_from']
        smtp_email_from = event['smtp_email_from']
        smtp_username = event['aws_ses_access_key_id']
        smtp_password = event['aws_ses_secret_access_key']
        smtp_email_to_list = event['smtp_email_to_list']
        aws_db_access_key_id = event['aws_db_access_key_id']
        aws_db_secret_access_key = event['aws_db_secret_access_key']
        try:
            departure_time = int(time.time()) + 60
            if not journey_reverse:
                url = self.url1.format(journey_origin, journey_destination,
                                       departure_time, google_api_key)
                map_url = self.url2.format(journey_origin, journey_destination)
            else:
                url = self.url1.format(journey_destination, journey_origin,
                                       departure_time, google_api_key)
                map_url = self.url2.format(journey_destination, journey_origin)
            map_url = map_url.replace(',', '')
            if DEBUG:
                print 'Invoking url: {0}\n'.format(url)
            response = requests.get(url, allow_redirects=False, verify=True)
        except requests.RequestException as e:
            print 'Connection failure: {0}\nExiting..'.format(e)
            die(event, e)

        if response.status_code != requests.codes.OK:
            print 'Request failure: Status {0}\nText {1}\nExiting..'.format(
                response.status_code, response.text)
            die(event)

        response_json = response.json()
        if DEBUG:
            print '{}'.format(response_json)

        try:
            # begin db_item ensure db_item exists
            db_table = event[DBTABLE]
            alert_type1 = alert_type
            if journey_reverse:
                alert_type1 = '{}_reverse'.format(alert_type)
            db_item = None
            if db_table.query_count(alert_type__eq=alert_type1) > 0:
                db_item = db_table.lookup(alert_type1)
            if db_item is None:
                db_table.put_item(data={'alert_type':alert_type1})
                db_item = db_table.lookup(alert_type1)
            # end db_item
            distance_m = response_json['routes'][0]['legs'][0]['distance']\
                                      ['text']
            normal_duration_s = response_json['routes'][0]['legs'][0]\
                                      ['duration']['value']
            normal_duration_m = normal_duration_s/60
            traffic_duration_s = response_json['routes'][0]['legs'][0]\
                                      ['duration_in_traffic']['value']
            traffic_duration_m = traffic_duration_s/60
            print 'distance {} normal duration {} min traffic duration {} min'.\
                format(distance_m, normal_duration_m, traffic_duration_m)
            # To ensure we r talking to a live taffic value use a threshold with
            # duration > 5 minute. duration < 30 minute between 6:00am to 7:00am
            if traffic_duration_m > 5:
                if traffic_duration_m > normal_duration_m*journey_delay_factor:
                    uts = int(time.time())
                    if not db_item.get(ALERTED):
                        c1 = 1
                        if db_item.get(MTIME):
                            # catch exception to take care of corrupted file
                            # or file with invalid content
                            try:
                                mtime = int(db_item[MTIME])
                                if (uts - mtime) < self.hr1:
                                    c1 = int(db_item[COUNT])
                                    c1 += 1
                                    if c1 >= self.th1:
                                        print 'BEGIN:: Sending sms at time {}'\
                                            'to '\
                                            '{}'.format(uts, smtp_email_to_list)
                                        # send sms and delete file
                                        ec1 = EmailClient(smtp_server,
                                                          smtp_port,
                                                          smtp_username,
                                                          smtp_password)
                                        ec1.send_message(smtp_email_from,
                                                         smtp_email_to_list,
                                                         '{}: Heavy Traffic'
                                                         .format(ALERT)
                                                         , 'Journey time is {}'
                                                         ' minutes. {}'
                                                         .format(\
                                                         traffic_duration_m,\
                                                         map_url))
                                        ec1.close()
                                        print 'DONE:: Sending sms'
                                        c1 = 1
                                        # create an alerted flag file to send
                                        # sms only once, when this script
                                        # detects a normal traffic the alerted
                                        # flag is deleted (see below). The flag
                                        # is also deleted if it is more than
                                        # two hours old (see below)
                                        db_item[ALERTED] = True
                            except Exception, ex1:
                                print ex1
                        db_item[MTIME] = uts
                        db_item[COUNT] = c1
                        db_item.save()
                    else:
                        # if alerted flag is older than hr1 remove it
                        mtime = int(db_item[MTIME])
                        if DEBUG:
                            print '(uts {} - mtime {}) > self.hr1 {}'\
                                  .format(uts, mtime, self.hr1)
                        if (uts - mtime) > self.hr1:
                            del db_item[ALERTED]
                            db_item[COUNT] = 0
                            db_item[MTIME] = uts
                            db_item.save()
                            print 'removed old alerted flag created at {}!'\
                                  .format(mtime)
                        else:
                            print 'alerted flag exists, created at {} current'\
                                  ' time {}. skip!'.format(mtime, uts)
                else:
                    # traffic situation is normal clear up alerted flag
                    if db_item.get(ALERTED):
                        del db_item[ALERTED]
                        db_item[COUNT] = 0
                        db_item[MTIME] = uts
                        db_item.save()
        except Exception, ex2:
            print ex2
            print >> sys.stderr, traceback.print_exc()
            print >> sys.stderr, '\n'
            traceback.print_stack(file=sys.stderr)
            sys.stderr.flush()
            die(event, ex2)
        return '{} min'.format(traffic_duration_m)

def open_init_db(event):
    if USELOCALDB:
        conn = DynamoDBConnection(aws_access_key_id='foo',
                                  aws_secret_access_key='bar',
                                  host='localhost',
                                  port=8000,
                                  is_secure=False)
    else:
        aws_db_access_key_id = event['aws_db_access_key_id']
        aws_db_secret_access_key = event['aws_db_secret_access_key']
        aws_db_region = event['aws_db_region']
        aws_db_reg = RegionInfo(
            name=aws_db_region,
            endpoint='dynamodb.%s.amazonaws.com'%(aws_db_region))
        conn = DynamoDBConnection(region=aws_db_reg,
                                  aws_access_key_id=aws_db_access_key_id,
                                  aws_secret_access_key=aws_db_secret_access_key,
                                  is_secure=True)
    table_names = None
    if conn.list_tables().get('TableNames'):
        table_names = conn.list_tables()['TableNames']
    # Ensure table exists
    if table_names is None or DBTABLE not in table_names:
        db_table = Table.create(DBTABLE, schema=[HashKey('alert_type')],
                                throughput={'read':1, 'write':1},
                                connection=conn)
    else:
        db_table = Table(DBTABLE, connection=conn)
    # pass db table as part of event
    event[DBTABLE] = db_table

def die(event, ex=None):
    close_db(event)
    print >> sys.stderr, 'ealerts::die: exception {}'.format(ex)
    sys.exit(1)

def close_db(event):
    db_table = event[DBTABLE]
    db_table.connection.close()

def main_handler(event, context):
    open_init_db(event)
    alert_type = event['alert_type']
    globals()[alert_type]().handler(event, None)
    close_db(event)

if __name__ == '__main__':
    eventf = sys.argv[1]
    with open(eventf) as event_file:
        import json
        event1 = json.load(event_file)
        if DEBUG:
            print event1
        main_handler(event1, None)
