__all__ = ['set_options']

import os

class set_options:
	def __init__(self, dictionary):
		for attr, value in dictionary.items():
			setattr(self, attr, value)