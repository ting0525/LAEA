import requests, threading, _thread, traceback

class CSMError(Exception):
	pass

class CSMAPI():

	IoTtalk = requests.Session()
	IoTtalk.keep_alive = False
	SessionList = {}; 

	def __init__(self, ENDPOINT=None, TIMEOUT=10):
		self.ENDPOINT = ENDPOINT
		self.TIMEOUT = TIMEOUT
		self.SessionList = {};
	
	def SessionListcheck(self, threadID):
		if str(_thread.get_ident()) not in self.SessionList.keys():
			self.SessionList[threadID] = requests.Session();
			self.SessionList[threadID].keep_alive = False;

	def register(self, mac_addr, profile, UsingSession=IoTtalk):
		#print("register: ",threading.get_ident());
		#with open('debug.txt', "a+") as f:
		#	f.write("register:%s\n" % thread.get_ident())
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		   
		r = UsingSession.post(
			self.ENDPOINT + '/' + mac_addr,
			json={'profile': profile}, timeout=self.TIMEOUT
		)
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("register error\n")
			raise CSMError(r.text)
		r.close()
		with open('print.txt', "a+") as f:
			f.write("Register to IoTtalk server:%s\n" % self.ENDPOINT)
		return True


	def deregister(self, mac_addr, UsingSession=IoTtalk):
		#print("deregister: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		
		r = UsingSession.delete(self.ENDPOINT + '/' + mac_addr)
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("deregister error\n")
			raise CSMError(r.text)
		r.close()
		return True


	def push(self, mac_addr, df_name, data, UsingSession=IoTtalk):
		#print("push: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		with open('print.txt', "a+") as f:
			f.write("mac_addr is: %s\ndf_name is: %s\n" % (mac_addr,df_name))
		r = UsingSession.put(
			self.ENDPOINT + '/' + mac_addr + '/' + df_name,
			json={'data': data}, timeout=self.TIMEOUT,
			headers={'Connection': 'close'}
		)
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("push error\n")
			raise CSMError(r.text)
		r.close()
		return True


	def pull(self, mac_addr, df_name, UsingSession=IoTtalk):
		#print("pull: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		
		r = UsingSession.get(self.ENDPOINT + '/' + mac_addr + '/' + df_name, timeout=self.TIMEOUT, headers={'Connection': 'close'})
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("pull error\n")
			raise CSMError(r.text)
		r.close()
		return r.json()['samples']


	def get_alias(self, mac_addr, df_name, UsingSession=IoTtalk):
		#print("get_alias: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		
		r = UsingSession.get(self.ENDPOINT + '/get_alias/' + mac_addr + '/' + df_name, timeout=self.TIMEOUT)
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("get_alias error\n")
			raise CSMError(r.text)
		r.close()
		return r.json()['alias_name']


	def set_alias(self, mac_addr, df_name, s, UsingSession=IoTtalk):
		#print("set_alias: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		
		r = UsingSession.get(self.ENDPOINT + '/set_alias/' + mac_addr + '/' + df_name + '/alias?name=' + s, timeout=self.TIMEOUT)
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("set_alias error\n")
			raise CSMError(r.text)
		r.close()
		return True


	def tree(self, UsingSession=IoTtalk):
		#print("tree: ",threading.get_ident());
		threadID = str(_thread.get_ident());
		self.SessionListcheck(threadID);
		UsingSession = self.SessionList[threadID];
		
		r = UsingSession.get(self.ENDPOINT + '/tree')
		if r.status_code != 200: 
			r.close()
			with open('debug.txt', "a+") as f:
				f.write("tree error\n")
			raise CSMError(r.text)
		r.close()
		return r.json()
