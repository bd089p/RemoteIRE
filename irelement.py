# -*- coding: utf-8 -*-

import json
import urllib2
import sys
import serial
import os
import time
import signal
import argparse
import logging
import logging.handlers

import threading

here = os.path.abspath(os.path.dirname(__file__))
devices_dir =  here+"/devices"

http_status_ok = 200

# parse options
parser = argparse.ArgumentParser(description='remote IR agent')
parser.add_argument('-s', '--server', action="store", dest="server", help="WebAPI host", default="localhost")
parser.add_argument('-p', '--port', action="store", dest="port", help="WebAPI port", default="8888")
parser.add_argument('-d', '--device', action="store", dest="irdev", help="device file to send IR", default="/dev/ttyACM0")
parser.add_argument('-t', '--temperature', action="store", dest="temp", help="temperature measurement and notification interval in sec", default=0)

args = parser.parse_args()

#logging
logfile = here + "/logs/iragent.log"
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')

rfh = logging.handlers.RotatingFileHandler(
    filename=logfile,
    maxBytes=2000000,
    backupCount=3
)
rfh.setLevel(logging.DEBUG)
rfh.setFormatter(formatter)
logger.addHandler(rfh)

stdout = logging.StreamHandler()
stdout.setLevel(logging.DEBUG)
stdout.setFormatter(formatter)
logger.addHandler(stdout)

def handle_SIGINT(signal, frame) :
   logger.info("shutting down...")
   sys.exit(0)

def playIR(path):
  msg = "Failed"
  try:
    ser = serial.Serial(args.irdev, 9600, timeout = 1)
    if path and os.path.isfile(path):
      logger.info("Playing IR by %s ..." % path)
      f = open(path)
      data = json.load(f) 
      f.close()
      recNumber = len(data['data'])
      rawX = data['data']
  
      ser.write("n,%d\r\n" % recNumber)
      ser.readline()
  
      postScale = data['postscale']
      ser.write("k,%d\r\n" % postScale)
      msg = ser.readline()
      
      for n in range(recNumber):
          bank = n / 64
          pos = n % 64

          if (pos == 0):
            ser.write("b,%d\r\n" % bank)
      
          ser.write("w,%d,%d\n\r" % (pos, rawX[n]))
      
      ser.write("p\r\n")
      msg = ser.readline()
      ser.close()
  except Exception as e:
    logger.error("Exception caught: %s" % str(e))
#  finally:

  return msg

def measureTemperature():
  ser = serial.Serial(args.irdev, 9600, timeout = 1)
  ser.write("T\r\n")
  time.sleep(1)
  raw = ser.readline()
  status = ser.readline().rstrip()
  celsiusTemp = None
  celsiusTemp = ((5.0 / 1024.0 * float(raw)) - 0.4) / 0.01953 
  ser.close

  return celsiusTemp

def initialize_remote_entry():
  b = False
  try:
    logger.info("initializing device entries...")
    # initialize device entries.
    init_device_url = 'http://'+args.server+':'+args.port+'/remocon/device/init'
    logger.info("URL: %s" % init_device_url)
    req = urllib2.Request(init_device_url)
    req.add_header('Content-Type', 'application/json')
    res = urllib2.urlopen(req, json.dumps({}))
    if res.getcode() == http_status_ok:
      logger.info("Success")
    else:
      logger.info("Failed")
    res.close()
    b = True
  except Exception as e:
    logger.error("Exception caught: %s" % str(e))
#    sys.exit(1)
#  finally:

  return b

def create_remote_entiry():
  b = False
  # create device entries.
  for dirpath, dirs, files in os.walk(devices_dir, followlinks=True):
    if dirpath != devices_dir:
      device = os.path.basename(dirpath)
      commands = []
      for filename in files:
        if ".json" in filename:
          command = os.path.splitext(filename)[0]
          commands.append(command)
  
      commands.sort()
      device_json = {
          'device': device,
          'commands': commands
          }
  
      try:
        logger.info("creating device entry for %s ..." % device)
        regist_device_url = 'http://'+args.server+':'+args.port+'/remocon/device/add'
        logger.info("URL: %s" % regist_device_url)
        req = urllib2.Request(regist_device_url)
        req.add_header('Content-Type', 'application/json')
        res = urllib2.urlopen(req, json.dumps(device_json))
        if res.getcode() == http_status_ok:
          logger.info("Success")
        else:
          logger.info("Failed")
        res.close()
        b = True
      except Exception as e:
        logger.error("Exception caught: %s" % str(e))
#        sys.exit(1)
#      finally:

  return b

# start
signal.signal(signal.SIGINT, handle_SIGINT)
if not initialize_remote_entry(): sys.exit(1)
if not create_remote_entiry(): sys.exit(1)
#initialize_remote_entry()
#create_remote_entiry()

class TemperatureHandler(threading.Thread):

  notification_url = 'http://'+args.server+':'+args.port+'/remocon/device/notify'

  def __init__(self):
    threading.Thread.__init__(self) 

  def run(self):
    # temperature loop
    while 1:
      try:
        temperature = measureTemperature()
        formatedTemperature = "{:4.1f}".format(temperature)
        logger.info("current temperature: %s" % formatedTemperature)
        logger.info("URL: %s" % self.notification_url)
        req = urllib2.Request(self.notification_url)
        req.add_header('Content-Type', 'application/json')
        notify_json = {
            'date': int(time.time()),
            'type': 'temperature',
            'value': formatedTemperature
            }
        res = urllib2.urlopen(req, json.dumps(notify_json))
        if res.getcode() == http_status_ok:
          logger.info("Success")
        else:
          logger.info("Failed")
        res.close()
      except Exception as e:
        logger.error("Exception caught: %s" % str(e))

      time.sleep(float(args.temp))

if args.temp >= 60:
  th = TemperatureHandler()
  th.daemon = True
  th.start()

while 1:
  try:
    logger.info("waiting remocon request...")
    get_request_url = 'http://'+args.server+':'+args.port+'/remocon/request'
    logger.info("URL: %s" % get_request_url)
    res = urllib2.urlopen(get_request_url)

    if res.getcode() == http_status_ok:
      logger.info("Success")
      data_json = json.loads(res.read())
      action = data_json['action']
      device = data_json['device']
      command = data_json['command']
      ir_json_path = devices_dir+"/"+device+"/"+command+".json"
      res.close()
      logger.info("remocon action: %s" % action)

      if action == "control" and os.path.isfile(ir_json_path):
        logger.info("switch %s %s" % (device, command))
        remocon_status = playIR(ir_json_path)
        history_json = {
            'date': int(time.time()),
            'device': device,
            'command': command,
            'status': remocon_status
            }
        history_url = 'http://'+args.server+':'+args.port+'/remocon/system/history'
        logger.info("URL: %s" % history_url)
        req = urllib2.Request(history_url)
        req.add_header('Content-Type', 'application/json')
        res = urllib2.urlopen(req, json.dumps(history_json))
      elif action == "shutdown":
        break
      else:
        if action != "retry": logger.warn("unknown action: %s" % action)
      #json.loads(data_json)
    else:
      logger.error("Failed: HTTP STATUS CODE - %d" % res.getcode())

    res.close()
  except Exception as e:
    logger.error("Exception caught: %s" % str(e))
    time.sleep(30)
    create_remote_entiry()
#  finally:
#    response.close

