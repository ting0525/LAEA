# -*- coding: UTF-8 -*-
import requests, time, csmapi, random, threading, _thread, socket, uuid

class DAN:
	def __init__(self):
		self.state = 'SUSPEND'
		self.selectedDF = []
		self.control_channel_timestamp = None
		self.timestamp = {}
		self.profile = {}
		self.mac = None
		self.IP = None
		self.control_thread = None;
		self.control_thread_runing = True;
		self.csmapi = csmapi.CSMAPI()

	def control_channel(self):
		#print ('Control Channel Runing')
		#ControlSession=requests.Session()
		#ControlSession.keep_alive = False
		ControlSleep = 2;
		while True:
			time.sleep(ControlSleep)
			try:
				#print("SessionList:",self.csmapi.SessionList)
				#print("control_channel:",str(threading.get_ident()))
				ch = self.csmapi.pull(self.mac, '__Ctl_O__')
				if ch != []:
					if self.control_channel_timestamp == ch[0][0]: continue
					self.control_channel_timestamp = ch[0][0]
					self.state = ch[0][1][0]
					if self.state == 'SET_DF_STATUS' :
						self.csmapi.push(self.mac, '__Ctl_I__',['SET_DF_STATUS_RSP',{'cmd_params':ch[0][1][1]['cmd_params']}])
						DF_STATUS = list(ch[0][1][1]['cmd_params'][0])
						self.selectedDF = []
						index=0			
						for STATUS in DF_STATUS:
							if STATUS == '1':
								self.selectedDF.append(self.profile['df_list'][index])
							index=index+1
						ControlSleep = 2;
					elif self.state == 'RESUME':
						ControlSleep = 60;
					else:
						ControlSleep = 2;
				if self.control_thread_runing != True:
					break;
			except Exception as e:
				time.sleep(5)
				typestr = str(e);
				
				#pos = typestr.find("HTTPConnectionPool",0,300)
				#if pos == -1:
					#print ("control_channel:",e)
				
				pos = typestr.find("mac_addr not found",0,300)
				if pos != -1:
					time.sleep(60)
					if self.control_thread_runing != True:
						break;
					self.device_registration_with_retry(self.profile, self.IP, self.mac)

	def get_mac_addr(self):
		mac = uuid.uuid4().hex
		# mac = ''.join(("%012X" % mac)[i:i+2] for i in range(0, 12, 2))
		return mac

	def detect_local_ec(self):
		EASYCONNECT_HOST=None
		UDP_IP = ''
		UDP_PORT = 17000
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		s.bind((UDP_IP, UDP_PORT))
		while EASYCONNECT_HOST==None:
			#print ('Searching for the IoTtalk server...')
			data, addr = s.recvfrom(1024)
			if str(data.decode()) == 'easyconnect':
				EASYCONNECT_HOST = 'http://{}:9999'.format(addr[0])
				self.csmapi.ENDPOINT=EASYCONNECT_HOST
				#print('IoTtalk server = {}'.format(self.CSMAPI.ENDPOINT))

	def register_device(self):
		if self.csmapi.ENDPOINT == None: self.detect_local_ec()

		if self.profile['d_name'] == None: 
			self.profile['d_name']= str(int(random.uniform(1, 100)))+'.'+ self.profile['dm_name']

		for i in self.profile['df_list']: 
			self.timestamp[i] = ''

		#with open('debug.txt', "a+") as f:
		#	f.write("IoTtalk Server:%s\n" % self.csmapi.ENDPOINT)
		#with open('debug.txt', "a+") as f:
		#	f.write("ident:%s\n" % thread.get_ident())
        
		#print('IoTtalk Server = {}'.format(self.csmapi.ENDPOINT))
		if self.control_thread_runing != True:
			return False

		if self.csmapi.register(self.mac, self.profile):
			#print ('This device has successfully registered.')
			#print ('Device name = ' + self.profile['d_name'])
			#print("register:",str(threading.get_ident()))
	
			if self.control_thread == None: 
				self.control_thread=threading.Thread(target=self.control_channel)
				self.control_thread.daemon = True
				self.control_thread.start()
				
			return True
		else:
			with open('debug.txt', "a+") as f:
				f.write("csmapi.register: failed\n")
			#print ('Registration failed.')
			return False

	def device_registration_with_retry(self, profile=None, IP=None, addr=None):
		if profile == None or IP == None:
			#print("profile = ",profile)
			#print("IP = ", IP)
			#print('IoTtalk server IP and device profile can not be ignore!')
			return
		self.mac = addr if addr != None else self.get_mac_addr()	
		self.profile = profile
		self.IP = IP
		#print(profile)
		self.csmapi.ENDPOINT = 'http://' + IP + ':9999'
		success = False
		while not success:
			try:
				self.register_device()
				success = True
			except Exception as e:
				stre = str(e)
				#print ('Attach failed: '),
				#print (e)
			time.sleep(5)

	def pull(self, FEATURE_NAME):
		data =None;
		
		#if(self.state != 'RESUME'):
		#	time.sleep(5);
		#	self.state = 'RESUME';
		#print("pull:",str(threading.get_ident()))	
		try:
			data = self.csmapi.pull(self.mac, FEATURE_NAME) if self.state == 'RESUME' else []
		except Exception as e:
			#print (e)
			#print ("pull error:",e)
			typestr = str(e);
			pos = typestr.find("mac_addr not found",0,100)
			if pos != -1:
				time.sleep(60)
				if self.control_thread_runing != True:
					return None
				self.device_registration_with_retry(self.profile, self.IP, self.mac)
				return None
			else:
				raise e;

		if data != []:
			if self.timestamp[FEATURE_NAME] == data[0][0]:
				return None
			self.timestamp[FEATURE_NAME] = data[0][0]
			if (data[0][1] != [] and data[0][1][3]!=''):
				return data[0][1]
			else: return None
		else:
			return None

	def push(self, FEATURE_NAME, *data):
		#if(self.state != 'RESUME'):
		#	time.sleep(5);
		#	self.state = 'RESUME';
		#print("push:",str(threading.get_ident()))
		if self.state == 'RESUME':
			try:
				return self.csmapi.push(self.mac, FEATURE_NAME, list(data))
			except Exception as e:
				#print (e)
				#print ("push error:",e)
				typestr = str(e);
				pos = typestr.find("mac_addr not found",0,100)
				if pos != -1:
					time.sleep(60)
					if self.control_thread_runing != True:
						return None
					self.device_registration_with_retry(self.profile, self.IP, self.mac)
					return None
				else:
					raise e;
		else: return None

	def get_alias(self, FEATURE_NAME):
		aliasreturn =None;
		
		#if(self.state != 'RESUME'):
		#	time.sleep(5);
		#	self.state = 'RESUME';
		#print("get_alias:",str(threading.get_ident()))	
		try:
			aliasreturn = self.csmapi.get_alias(self.mac, FEATURE_NAME)
		except Exception as e:
			#print (e)
			#print ("get alias error:",e)
			typestr = str(e);
			pos = typestr.find("mac_addr not found",0,100)
			if pos != -1:
				time.sleep(60)
				if self.control_thread_runing != True:
					return None
				self.device_registration_with_retry(self.profile, self.IP, self.mac)
				return None
			else:
				raise e;
		else:
			return aliasreturn

	def set_alias(self, FEATURE_NAME, alias):
		aliasreturn =None;
		
		#if(self.state != 'RESUME'):
		#	time.sleep(5);
		#	self.state = 'RESUME';
		#print("set_alias:",str(threading.get_ident()))	
		try:
			aliasreturn = self.csmapi.set_alias(self.mac, FEATURE_NAME, alias)
		except Exception as e:
			#print (e)
			#print ("set alias error:",e)
			typestr = str(e);
			pos = typestr.find("mac_addr not found",0,100)
			if pos != -1:
				time.sleep(60)
				if self.control_thread_runing != True:
					return None
				self.device_registration_with_retry(self.profile, self.IP, self.mac)
				return None
			else:
				raise e;
		else:
			return aliasreturn		
		
	def deregister(self):
		self.control_thread_runing = False;
		return self.csmapi.deregister(self.mac)

