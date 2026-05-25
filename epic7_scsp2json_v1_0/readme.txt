Epic7 scsp2json File Converter v.1.0
========================================

  Python need.

  Usage:
    python epic7_scsp2json.py [optional: options] <.scsp file for convert to json> <optional: filename for new .json file (result)>
    
      options:
        -minify    - [optional] json will be without indentation and spaces, just one loooooooooooooong string for save space (a little faster for internet?)
                                without that options json will be nice with indentation, convenient for reading in notepad
        -wtempfile - [optional] do not delete temporary file after work (unpacked scsp, adds ".unpacked" in ext)
        -e7herder  - [optional] sort elements in json-file like in e7herder (for compare)
                  
      <.scsp file for convert to json>       - [required] filename for file, what you want for convert to json
      <filename for new .json file (result)> - [optional] filename for new .json file (result)
                                                          if not specified then script take filename from .scsp file and add ".json" in ext
                                                          like: c1001.scsp > c1001.scsp.json
    Example:
      python epic7_scsp2json.py -minify c1001.scsp c1001.json
        > convert "c1001.scsp" to "c1001.json" and minify json-file
        
      python epic7_scsp2json.py c1001.scsp c1001.json
        > convert "c1001.scsp" to "c1001.json" without minify json-file for reading and edit in notepad later
        
      python epic7_scsp2json.py c1001.scsp
        > convert "c1001.scsp" to "c1001.scsp.json" without minify json-file for reading and edit in notepad later
  
  ========================================
  if someone need "readable json" from e7herder dump ( https://github.com/zklm/e7herder-issues/releases/tag/dump ), use this command:
    python -m json.tool "json filename" > "new readable json filename"
  example:
    python -m json.tool c1001.json > c1001.e7herder.json
  
  ========================================
  if lz4 not found:
    python -m pip install --upgrade pip
    pip install --upgrade setuptools
    pip install wheel
    pip install lz4
    
  [windows]: if can't install lz4, error with many nice words and something about Microsoft Visual C++ Tools:
     https://wiki.python.org/moin/WindowsCompilers 
     download ms vs build tools ( https://visualstudio.microsoft.com/visual-cpp-build-tools/ )
     need to install "dev classic apps C++" only
     reboot
     try again (must be working now): pip install lz4
