# головной модуль, распаковывающий scsp и передающий результат на обработку дальше в другие модули, заточенные под определённую версию spine

import codecs, mmap, os, platform, struct, sys
import json
import lz4.block

import _epic7_scsp2json_funcs as _scsp_funcs
import _epic7_scsp2json_v2_1_27 as _scsp_v2_1_27


def DecryptSCSP(file4convert_, file4convert_decrypted): # распаковка данных через lz4
  mfilesize   = os.path.getsize(file4convert_)
  if platform.system() == 'Windows':
    mfd           = os.open(file4convert_, os.O_RDONLY | os.O_BINARY)
    mfile         = mmap.mmap(mfd, 0, access=mmap.ACCESS_READ)
  else:
    mfd           = os.open(file4convert_, os.O_RDONLY)
    mfile         = mmap.mmap(mfd, 0, prot=mmap.PROT_READ)

  # параметры компрессии
  tempo = mfile.read(4)
  decompressedLength = struct.unpack("@I", tempo)[0]
  tempo = mfile.read(4)
  compressedLength   = struct.unpack("@I", tempo)[0]
    
  input  = mfile.read(compressedLength) # загружаем в память запакованную область
  output = lz4.block.decompress(input, uncompressed_size=decompressedLength) # распаковываем
  
  mfile.close()
  os.close(mfd)
  
  if platform.system() == 'Windows':
    mfk                 = os.open(file4convert_decrypted, os.O_CREAT | os.O_RDWR | os.O_BINARY)
  else:
    mfk                 = os.open(file4convert_decrypted, os.O_CREAT | os.O_RDWR)
    
  os.truncate(mfk, 0) # зануляем файл, если был
  os.write(mfk, output)
  os.close(mfk)

def scsp2json_decrypt(file4convert_, argv_wtempfile, argv_e7herder):
  file_decrypted = file4convert_ + ".unpacked"
  
  DecryptSCSP(file4convert_, file_decrypted)
  
  if platform.system() == 'Windows':
    mfd           = os.open(file_decrypted, os.O_RDONLY | os.O_BINARY)
    mfile         = mmap.mmap(mfd, 0, access=mmap.ACCESS_READ)
  else:
    mfd           = os.open(file_decrypted, os.O_RDONLY)
    mfile         = mmap.mmap(mfd, 0, prot=mmap.PROT_READ)

  pos4RefStrings  = _scsp_funcs._scsp_readInt(mfile) + 8 # объем в байтах всех блоков файла, за исключением блока служебных меток. 
                                                         # прибавляем 8 байт, чтобы получить фактический адрес блока со списком служебных меток
  size4RefStrings = _scsp_funcs._scsp_readInt(mfile)     # общий размер в байтах, занятый списком служебных меток (метки разделяются h00)
  
  refStrings     = _scsp_funcs._scsp_readRefStrings(mfile, pos4RefStrings, size4RefStrings)
  
  mfile.close()
  os.close(mfd)

  print("SCSP format in file:", refStrings[1].decode("utf-8", "ignore")) # уведомляем о версии spine, использованной при генерации scsp
  
  result = {}
  if (refStrings[1] == b"2.1.27.scsp"):
    result = _scsp_v2_1_27.ConvertSCSPtoJSON(file_decrypted, argv_e7herder)
  else: # останов работы, нужного модуля для версии spine этого файла пока нет
    if (not argv_wtempfile): os.remove(file_decrypted) # освобождаем место, удаляем распакованный scsp
    print("New format? Script is halted.")
    
    sys.exit(1)
  '''
  elif (refStrings[1] == b"3.8.95.scsp"):
    ConvertSCSPtoJSON_4v3_8_95(file4convert_, mfile, refStrings_raw, refStrings)
  '''
  
  if (not argv_wtempfile): os.remove(file_decrypted) # освобождаем место, удаляем распакованный scsp
  
  return result

# основная функция модуля, использовать для запуска
def scsp2json_start(file4convert_, filename4json, argv_minify, argv_wtempfile, argv_e7herder):
  json4save = scsp2json_decrypt(file4convert_, argv_wtempfile, argv_e7herder)

  # сохраняем результат
  if argv_minify:
    with open(filename4json, 'w', encoding='utf-8') as f:
      json.dump(json4save, f, ensure_ascii=False)
  else:
    with open(filename4json, 'w', encoding='utf-8') as f:
      json.dump(json4save, f, ensure_ascii=False, indent=4)
  