# модуль с функциями под Epic7_scsp2json

import codecs, mmap, os, platform, struct, sys
from itertools import cycle
import json

def _scsp_skipUnknowns(input, count_): # just for skip some strange unknown blocks
  tempo = input.read(count_)

def _scsp_readByte(input):
  tempo = input.read(1)
  return int.from_bytes(tempo, byteorder='little', signed=False)

def _scsp_readInt(input):
  tempo = input.read(4)
  #print(tempo)
  return struct.unpack('@I', tempo)[0]

def _scsp_readShortInt(input):
  tempo = input.read(2)
  #print(tempo)
  return struct.unpack('@H', tempo)[0]
  
def _scsp_readFloat(input):
  tempo = input.read(4)
  return struct.unpack('@f', tempo)[0]
  
def _scsp_readRefStrings_raw(input, pos4RefStrings, size4RefStrings):
  input.seek(pos4RefStrings)
  tempo = input.read(size4RefStrings) # загружаем строку без дробления, сохраняем разделитель #00
  return tempo
  
def _scsp_readRefStrings(input, pos4RefStrings, size4RefStrings):
  tempo = _scsp_readRefStrings_raw(input, pos4RefStrings, size4RefStrings)
  tempo = tempo.split(b'\x00') # загружаем строку, дробим её на части на основе разделителя #00
  return tempo

def _scsp_extract_from_RefStrings(refStrings_raw, startpos4RefString):
  tempo = refStrings_raw[startpos4RefString:]
  tempo = tempo.split(b'\x00') # дробим на части на основе разделителя #00
  return tempo[0].decode("utf-8", "ignore")

def _scsp_4fuckingfloats2rgba(fR_, fG_, fB_, fA_): # i hate that genius dude, who came up with "RGBa to float values" idea
  RBGa_ =          round(fR_ * 255)  << 8 # R
  RBGa_ = (RBGa_ + round(fG_ * 255)) << 8 # G
  RBGa_ = (RBGa_ + round(fB_ * 255)) << 8 # B
  RBGa_ = (RBGa_ + round(fA_ * 255))      # A
  
  return '{:x}'.format(RBGa_).upper() # text like: FF5BA125
  
def _scsp_remove_float_zero (fl_var_): # clean values like 0.0, 3.0, 7.0 etc to like > 0, 3, 7
  import math
  result = fl_var_
  # Handle NaN and Inf safely
  if not math.isnan(result) and math.isfinite(result):
    if (round(result) == fl_var_): result = round(result)
  
  return result

def _scsp_json_key_by_id(json_ar_, key_id_): # search keyname by id (need for animations block)
  result = ""
  ind = 0
  for key_ in json_ar_.keys(): 
    if (ind == key_id_): result = key_
    ind = ind + 1
    
  return result
  
def sort_animations_json (json_ar_, depth = 0): # sorting for compare result with old json from e7herder
  depth_max = 4
  result = {}
  
  if (depth == 1):
    for key_ in json_ar_.keys(): 
      result.update({ key_ : json_ar_[key_] })
      if (depth < depth_max):
        result[key_] = sort_animations_json (json_ar_[key_], depth + 1)
  if (depth == 4):
    tempo  = json.dumps(json_ar_, sort_keys=True)
    result = json.loads(tempo)  
  else:
    for key_ in sorted(json_ar_.keys()): 
      result.update({ key_ : json_ar_[key_] })
      if (depth < depth_max):
        result[key_] = sort_animations_json (json_ar_[key_], depth + 1)
  
  return result
  
def sort_skins_json (json_ar_, depth = 0): # sorting for compare result with old json from e7herder
  depth_max = 2
  result = {}
  
  for key_ in sorted(json_ar_.keys()): 
      result.update({ key_ : json_ar_[key_] })
      if (depth < depth_max):
        result[key_] = sort_skins_json (json_ar_[key_], depth + 1)
  
  return result
  
def argv_option_check(keyname_):
  result = False
  
  ind = 1
  while (ind < len(sys.argv) - 1):
    if (sys.argv[ind] == keyname_): result = True
    ind = ind + 1
  
  return result
