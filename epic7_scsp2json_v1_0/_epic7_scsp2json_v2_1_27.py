# scsp2json module 4 format "2.1.27.scsp"

'''
  Sorry, my English is not the best.
  
  scsp file (unpacked) format "2.1.27.scsp":
    [4 bytes]  - size of all blocks w/o RefStrings (bytes count, int)
    [4 bytes]  - size of RefStrings (bytes count, int)
    [4 bytes]  - count for bones (int)
    [4 bytes]  - count for ikConstraints / ik ? (int)
    [4 bytes]  - count for slots (int)
    [4 bytes]  - count for skins (int)
    [4 bytes]  - count for events ? (int)
    [4 bytes]  - count for animations (int)
    [40 bytes] - [unknown]
    [4 bytes]  - skeleton//width (float)
    [4 bytes]  - skeleton//height (float)
    [-------]  - array of bones
    [-------]  - array of slots
    [-------]  - array of skins
    [4 bytes]  - [unknown] (always #00 00 00 00 ?)
    [-------]  - array of animations
    [-------]  - RefStrings (startpos = [size of all blocks w/o RefStrings] + 8 bytes)
                 first RefString  - skeleton//hash
                 second RefString - skeleton//spine
  
  for blocks bellow:
  [*] (int > link to RefString*)                             - take that int-value and add to [RefStrings startpos] for find string-value (with h00 ending)
  [*] (int/shortint > id to element in array of XXXXX*)      - element's id in order of place in file, count starts from 0 (root?)
  [*] (float > need take 4 floats and convert that to RGBA*) - load 4 floats and use... something like _scsp_funcs._scsp_4fuckingfloats2rgba(R,G,B,A) func
  [*] (int > blend variants*)                                - variants: 0 - empty value, 1 - "additive", 2 - "multiply", 3 - "screen"
                 
  [array of bones (count in file header)]:
    [element of array]:
      [4 bytes] - length          (float)
      [4 bytes] - x               (float)
      [4 bytes] - y               (float)
      [4 bytes] - rotation        (float)
      [4 bytes] - scaleX          (float)
      [4 bytes] - scaleY          (float)
      [4 bytes] - ?flipX?         (int > bool)
      [4 bytes] - ?flipY?         (int > bool)
      [4 bytes] - inheritScale    (int > bool)
      [4 bytes] - inheritRotation (int > bool)
      [4 bytes] - name            (int > link to RefString*)
      [2 bytes] - parent          (shortint > id to element in array of bones*) (if like #FFFF -> empty value )
                 
  [array of slots (count in file header)]:
    [element of array]:
      [4 bytes] - name            (int > link to RefString*)
      [2 bytes] - bone            (shortint > id to element in array of bones*)
      [4 bytes] - attachment      (int > link to RefString*) (if like #FFFF and more -> empty value )
      [4 bytes] - color [R]       (float > need take 4 floats and convert that to RGBA*)
      [4 bytes] - color [G]       (float > need take 4 floats and convert that to RGBA*)
      [4 bytes] - color [B]       (float > need take 4 floats and convert that to RGBA*)
      [4 bytes] - color [A]       (float > need take 4 floats and convert that to RGBA*)
      [4 bytes] - blend           (int > blend variants*)
      
      
  I don't know true names for keys, so my pattern for skins block in description bellow:
    { "[skin name]" (default/angry/etc) : {
        "[skin's slot]" (rhair2/normal/etc) : {
          "[attachment's name]" (rhair1/1/etc) : {
            "name" : "[record name]",
            "path" : "[record path name]",
            ...
          }
        }
      }
    }
  And need to remember loading order for all records from "skins block". Required for analyze links in "animation block".

  [array of skins (count in file header)]:
    [element of array]:
      [4 bytes] - skin name       (int > link to RefString*)
      [2 bytes] - count for parts (shortint)
      [-------] - array of skin's slots
  
  [array of skin's slots (count in element above - [count for parts])]:
    [element of array]:
      [4 bytes] - attachment's name  (int > link to RefString*)
      [4 bytes] - skin's slot        (int > id to element in array of slots*)
      [4 bytes] - data type          (int, WARNING: next blocks depends on that)
      [4 bytes] - record name        (int > link to RefString*)
      [4 bytes] - record path name   (int > link to RefString*)
      
      if [data type] == 0 (SP_ATTACHMENT_REGION)
        [4 bytes]  - x               (float)
        [4 bytes]  - y               (float)
        [4 bytes]  - scaleX          (float)
        [4 bytes]  - scaleY          (float)
        [4 bytes]  - rotation        (float)
        [8 bytes]  - [unknown]
        [4 bytes]  - color [R]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [G]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [B]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [A]       (float > need take 4 floats and convert that to RGBA*)
        [8 bytes]  - [unknown]
        [4 bytes]  - width           (int)
        [4 bytes]  - height          (int)
        [72 bytes] - [unknown]
    
      if [data type] == 2 (SP_ATTACHMENT_MESH)
        [4 bytes]  - count for vertices          (int)
        [-------]  - array of vertices           (just float values)
        [4 bytes]  - hull                        (int)
        [-------]  - array of uvs, part 2 (TWO!) (just float values, use [count for vertices]) <- don't ask me why part TWO earlier than part ONE
        [-------]  - array of uvs, part 1 (ONE!) (just float values, use [count for vertices])
        [4 bytes]  - count for triangles         (int)
        [-------]  - array of triangles          (just int values)
        [4 bytes]  - color [R]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [G]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [B]       (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [A]       (float > need take 4 floats and convert that to RGBA*)
        [48 bytes] - [unknown]
        [4 bytes]  - width           (float)
        [4 bytes]  - height          (float)
    
      if [data type] == 3 (SP_ATTACHMENT_SKINNED_MESH)
        [4 bytes]  - count for bones          (int)
        [-------]  - array of bones           (just int values, ids of bones?)
        [4 bytes]  - count for weights        (int)
        [-------]  - array of weights         (just float values)
        [4 bytes]  - count for triangles      (int)
        [-------]  - array of triangles       (just int values)
        [4 bytes]  - count for uvs            (int)
        [-------]  - array of uvs             (just int values, !!! but [count for uvs] x2 !!! maybe it's like [x,y], two values for one "element")
        [4 bytes]  - hull                     (int)
        [4 bytes]  - color [R]                (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [G]                (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [B]                (float > need take 4 floats and convert that to RGBA*)
        [4 bytes]  - color [A]                (float > need take 4 floats and convert that to RGBA*)
        [48 bytes] - [unknown]
        [4 bytes]  - width                    (float)
        [4 bytes]  - height                   (float)
      
      
  And now where are here... animations block. And remember: we have 4 bytes (always #00 00 00 00?) for unknown reasons before that block.
  
  I don't know true names for keys, so my pattern for animations block in description bellow:
    { "[animation name]" (Idle/fire/etc) : {
        "slots" : {
          "[slot's name]" (rhair/Layer 10/etc) : {}
        }
        "bones" : {
          "[bone's name]" (bone10/bone21/etc) : {}
        }
        "ffd" : {
          "[skin's name]" (default/angry/etc) : {
            "[skin's slot]" (rhair2/normal/etc) : {
              "[attachment's name]" (rhair1/1/etc) : {}
            }
          }
        }
      }
    }
  
  [array of animations (count in file header)]:
    [element of array]:
      [4 bytes] - animation name                 (int > link to RefString*)
      [4 bytes] - [unknown]
      [4 bytes] - count for animation's elements (int)
      [-------] - array of animation's elements
      
  [array of animation's elements (count in [count for animation's elements])]:
    [element of array]:
      [4 bytes] - data type (int, WARNING: next blocks depends on that)

      if [data type] == 0 (SP_TIMELINE_SCALE)
        [4 bytes] - bone's name             (int > id to element in array of bones*) (need to take bone's value from key "name" and use it for fill [bone's name])
        [4 bytes] - count for bone's scales (int)
        [-------] - array of bone's scales
        [-------] - array of curves for bone
  
        [array of bone's scales (WARNING: count in [count for bone's scales] need to be divided by 3, don't ask me why)]:
          [element of array]:
            [4 bytes] - time (float)
            [4 bytes] - x    (float)
            [4 bytes] - y    (float)
  
        [array of curves for bone elements (WARNING: count in [count for bone's scales] need to be divided by 3 and then decrease by 1, don't ask me why)]:
          There can be 2 situation:
          1) first 2 bytes ~= #FF FE or #FF FF  <- no curves here, end of [animation's element]
          2) if not (1), then reuse that 2 bytes for parse first element of array
          
          [element of array]:
            [2 bytes] - curve (shortint, 0 - empty value, 1 - "stepped", 2 - [value1, value2, value3, value4] )
            If curve == 2 (SP_CURVE_BEZIER), need to load more:
            [4 bytes] - [unknown]
            [4 bytes] - value1 for curve (float)
            [4 bytes] - value2 for curve (float)
            [4 bytes] - value3 for curve (float)
            [4 bytes] - value4 for curve (float)
  
      if [data type] == 1 (SP_TIMELINE_ROTATE)
        [4 bytes] - bone's name             (int > id to element in array of bones*) (need to take bone's value from key "name" and use it for fill [bone's name])
        [4 bytes] - count for bone's rotates (int)
        [-------] - array of bone's rotates
        [-------] - array of curves for bone
  
        [array of bone's rotates (WARNING: count in [count for bone's rotates] need to be divided by 2, don't ask me why)]:
          [element of array]:
            [4 bytes] - time  (float)
            [4 bytes] - angle (float)
  
        [array of curves for bone elements (WARNING: count in [count for bone's rotates] need to be divided by 2 and then decrease by 1, don't ask me why)]:
          There can be 2 situation:
          1) first 2 bytes ~= #FF FE or #FF FF  <- no curves here, end of [animation's element]
          2) if not (1), then reuse that 2 bytes for parse first element of array
          
          [element of array]:
            [2 bytes] - curve (shortint, 0 - empty value, 1 - "stepped", 2 - [value1, value2, value3, value4] )
            If curve == 2 (SP_CURVE_BEZIER), need to load more:
            [4 bytes] - [unknown]
            [4 bytes] - value1 for curve (float)
            [4 bytes] - value2 for curve (float)
            [4 bytes] - value3 for curve (float)
            [4 bytes] - value4 for curve (float)

      if [data type] == 2 (SP_TIMELINE_TRANSLATE)
        [4 bytes] - bone's name             (int > id to element in array of bones*) (need to take bone's value from key "name" and use it for fill [bone's name])
        [4 bytes] - count for bone's translates (int)
        [-------] - array of bone's translates
        [-------] - array of curves for bone
  
        [array of bone's translates (WARNING: count in [count for bone's translates] need to be divided by 3, don't ask me why)]:
          [element of array]:
            [4 bytes] - time (float)
            [4 bytes] - x    (float)
            [4 bytes] - y    (float)
  
        [array of curves for bone elements (WARNING: count in [count for bone's translates] need to be divided by 3 and then decrease by 1, don't ask me why)]:
          There can be 2 situation:
          1) first 2 bytes ~= #FF FE or #FF FF  <- no curves here, end of [animation's element]
          2) if not (1), then reuse that 2 bytes for parse first element of array
          
          [element of array]:
            [2 bytes] - curve (shortint, 0 - empty value, 1 - "stepped", 2 - [value1, value2, value3, value4] )
            If curve == 2 (SP_CURVE_BEZIER), need to load more:
            [4 bytes] - [unknown]
            [4 bytes] - value1 for curve (float)
            [4 bytes] - value2 for curve (float)
            [4 bytes] - value3 for curve (float)
            [4 bytes] - value4 for curve (float)

      if [data type] == 3 (SP_TIMELINE_COLOR) <- yep, in scsp for spine v2: SP_TIMELINE_COLOR == 3
        [4 bytes] - slot's name             (int > id to element in array of slots*) (need to take slot's value from key "name" and use it for fill [slot's name])
        [4 bytes] - count for slot's colors (int)
        [-------] - array of slot's colors
        [-------] - array of curves for slot
      
        [array of slot's colors (WARNING: count in [count for slot's colors] need to be divided by 5, don't ask me why)]:
          [element of array]:
            [4 bytes] - time      (float)
            [4 bytes] - color [R] (float > need take 4 floats and convert that to RGBA*)
            [4 bytes] - color [G] (float > need take 4 floats and convert that to RGBA*)
            [4 bytes] - color [B] (float > need take 4 floats and convert that to RGBA*)
            [4 bytes] - color [A] (float > need take 4 floats and convert that to RGBA*)
  
        [array of curves for slot elements (WARNING: count in [count for slot's colors] need to be divided by 5 and then decrease by 1, don't ask me why)]:
          There can be 2 situation:
          1) first 2 bytes ~= #FF FE or #FF FF  <- no curves here, end of [animation's element]
          2) if not (1), then reuse that 2 bytes for parse first element of array
          
          [element of array]:
            [2 bytes] - curve (shortint, 0 - empty value, 1 - "stepped", 2 - [value1, value2, value3, value4] )
            If curve == 2 (SP_CURVE_BEZIER), need to load more:
            [4 bytes] - [unknown]
            [4 bytes] - value1 for curve (float)
            [4 bytes] - value2 for curve (float)
            [4 bytes] - value3 for curve (float)
            [4 bytes] - value4 for curve (float)
      
      if [data type] == 4 (SP_TIMELINE_ATTACHMENT) <- yep, in scsp for spine v2: SP_TIMELINE_ATTACHMENT == 4
        [4 bytes] - slot's name                  (int > id to element in array of slots*) (need to take slot's value from key "name" and use it for fill [slot's name])
        [4 bytes] - count for slot's attachments (int)
        [-------] - array of slot's attachments times (just float values)
        [-------] - array of slot's attachments names (int > link to RefString*) (if like #FFFF and more -> empty value )
        
        Need to connect times and names in blocks, 1 by 1. Like first time to first name, second time to second name, etc.
        
      if [data type] == 7 (SP_TIMELINE_FFD)
        [4 bytes] - count for ffd's times (int)
        [-------] - array of ffd's times (just float values)
        [4 bytes] - [unknown]
        [4 bytes] - count for ffd's vertices in one timeframe (int)
        [-------] - array of ffd's vertices (floats, listed sequentially, first part for first timeframe, next part for second timeframe, etc)
        [-------] - array of curves for ffd (listed sequentially, first part for first timeframe, next part for second timeframe, etc)
        [4 bytes] - skin's record id  (int > id to record in SPECIAL array of skins, metioned above*) <- need for fill keys [skin's name], [skin's slot] and [attachment's name]
            
        Need to connect times, vertices and curves in blocks, 1 by 1. 
        Like first timeframe to first blocks of vertices and curves, second block to second blocks of vertices and curves, etc.
            
        [array of curves for ffd elements]:
          There can be 2 situation:
          1) first 2 bytes ~= #FF FE or #FF FF  <- no curves here, end of [animation's element]
          2) if not (1), then reuse that 2 bytes for parse first element of array
          
          [element of array]:
            [2 bytes] - curve (shortint, 0 - empty value, 1 - "stepped", 2 - [value1, value2, value3, value4] )
            If curve == 2 (SP_CURVE_BEZIER), need to load more:
            [4 bytes] - [unknown]
            [4 bytes] - value1 for curve (float)
            [4 bytes] - value2 for curve (float)
            [4 bytes] - value3 for curve (float)
            [4 bytes] - value4 for curve (float)
  
  
  Well. Something like that. I could get a little confused in the description above, because I spent 5 hours on its layout.
  
  If anything raises doubts or questions: the working code can be found below.
  
'''
  

import codecs, mmap, os, platform, struct, sys
import json
import lz4.block  # https://wiki.python.org/moin/WindowsCompilers

import _epic7_scsp2json_funcs as _scsp_funcs

SP_ATTACHMENT_REGION       = 0
SP_ATTACHMENT_BOUNDING_BOX = 1
SP_ATTACHMENT_MESH         = 2
SP_ATTACHMENT_SKINNED_MESH = 3

SP_TIMELINE_SCALE        = 0
SP_TIMELINE_ROTATE       = 1
SP_TIMELINE_TRANSLATE    = 2
#SP_TIMELINE_ATTACHMENT   = 3
#SP_TIMELINE_COLOR        = 4
SP_TIMELINE_COLOR        = 3 # scsp
SP_TIMELINE_ATTACHMENT   = 4 # scsp
SP_TIMELINE_FLIPX        = 5
SP_TIMELINE_FLIPY        = 6
SP_TIMELINE_FFD          = 7
SP_TIMELINE_IKCONSTRAINT = 8

SP_CURVE_LINEAR  = 0
SP_CURVE_STEPPED = 1
SP_CURVE_BEZIER  = 2


def _scsp_readBones(input, refStrings_raw, count_bones, pos4start=88):
  result    = []

  input.seek(pos4start)
  
  bone_parents = []  # store parent indices for second pass
  ind = 0
  while (ind < count_bones):
    bone_length   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 2))
    bone_x        = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 2))
    bone_y        = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 2))
    bone_rotation = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 2))
    bone_scaleX   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
    bone_scaleY   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
    
    bone_FlipX    = (_scsp_funcs._scsp_readInt(input) > 0) # ?
    bone_FlipY    = (_scsp_funcs._scsp_readInt(input) > 0) # ?

    bone_inheritScale    = (_scsp_funcs._scsp_readInt(input) > 0)
    bone_inheritRotation = (_scsp_funcs._scsp_readInt(input) > 0)
    bone_link2ref        = _scsp_funcs._scsp_readInt(input)
    bone_parent          = _scsp_funcs._scsp_readShortInt(input)
    
    bone_name     = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, bone_link2ref)
    bones         = {"name" : bone_name}
    if (bone_length != 0):         bones["length"]          = bone_length
    if (bone_x != 0):              bones["x"]               = bone_x
    if (bone_y != 0):              bones["y"]               = bone_y
    if (bone_rotation != 0):       bones["rotation"]        = bone_rotation
    if (bone_scaleX != 1):         bones["scaleX"]          = bone_scaleX
    if (bone_scaleY != 1):         bones["scaleY"]          = bone_scaleY
    # bone_FlipX / bone_FlipY intentionally not emitted: Spine 3.8 removed per-bone flip fields
    # Translate Spine 2.x inherit booleans into Spine 3.8 `transform` enum.
    # Spine 3.8's runtime ignores inheritRotation/inheritScale; emitting them is
    # a no-op and causes upside-down heads, split weapons, drifting hair on rigs
    # authored with non-default inheritance.
    if (not bone_inheritScale) and (not bone_inheritRotation):
      bones["transform"] = "onlyTranslation"
    elif (not bone_inheritRotation):
      bones["transform"] = "noRotationOrReflection"
    elif (not bone_inheritScale):
      bones["transform"] = "noScale"
    
    result.append(bones)
    bone_parents.append(bone_parent)
    ind = ind + 1
  
  # Second pass: resolve parent references now that all bones exist
  for i in range(len(result)):
    bone_parent = bone_parents[i]
    if (bone_parent < 65535) and (bone_parent < len(result)):
      result[i]["parent"] = result[bone_parent]["name"]
    
  return result


def _scsp_readSlots(input, refStrings_raw, bones, count_slots):
  result    = []
  
  ind = 0
  while (ind < count_slots):
    slot_name_link2ref       = _scsp_funcs._scsp_readInt(input)
    slot_bone                = _scsp_funcs._scsp_readShortInt(input)
    slot_attachment_link2ref = _scsp_funcs._scsp_readInt(input)
    
    slot_color = _scsp_funcs._scsp_4fuckingfloats2rgba(_scsp_funcs._scsp_readFloat(input),
                                                       _scsp_funcs._scsp_readFloat(input),
                                                       _scsp_funcs._scsp_readFloat(input), 
                                                       _scsp_funcs._scsp_readFloat(input)) #RGBA
    
    slot_blendmode_mark      = _scsp_funcs._scsp_readInt(input)
    
    slot_name = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, slot_name_link2ref)
    
    slots = {"name" : slot_name, "bone" : bones[slot_bone]["name"]}
    
    if (slot_color != "FFFFFFFF"): slots["color"] = slot_color
    
    if   (slot_blendmode_mark == 1): slots["blend"] = "additive"
    elif (slot_blendmode_mark == 2): slots["blend"] = "multiply"
    elif (slot_blendmode_mark == 3): slots["blend"] = "screen"
    
    # Null-attachment sentinel is the uint32 0xFFFFFFFF; do NOT use 65535
    # — combat rigs ship refstring tables ≥ 128 KB and legitimate byte
    # offsets routinely exceed 65535. The old `< 65535` check silently
    # voided every slot attachment whose ref-string lived past the 64 KB
    # mark, producing rigs with no setup-pose attachments.
    if (slot_attachment_link2ref != 0xFFFFFFFF):
        slots["attachment"] = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, slot_attachment_link2ref)
    
    
    result.append(slots)
    
    ind = ind + 1
    
  return result


def _scsp_readSkins(input, refStrings_raw, bones, slots, count_skins):
  result      = {}
  result4ffds = []
  
  ind = 0
  while (ind < count_skins):
    skin_name_link2ref       = _scsp_funcs._scsp_readInt(input)
    count_skin_sub           = _scsp_funcs._scsp_readShortInt(input)
    skin_name                = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, skin_name_link2ref)

    skins = { skin_name : {} }
    
    ind_sub = 0
    while (ind_sub < count_skin_sub):
      bones4skin     = []
      weights4skin   = []
      triangles4skin = []
      uvs4skin       = []
      vertices4skin  = []
      
      skin_attachment_link2ref = _scsp_funcs._scsp_readInt(input)
      skin_slot                = _scsp_funcs._scsp_readInt(input)
    
      skin_mode                = _scsp_funcs._scsp_readInt(input)
      skin_item_name_link2ref  = _scsp_funcs._scsp_readInt(input)
      skin_item_path_link2ref  = _scsp_funcs._scsp_readInt(input)
    
      if (skin_mode == SP_ATTACHMENT_REGION): # default
        skin_x        = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
        skin_y        = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
        skin_scaleX   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
        skin_scaleY   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
        skin_rotation = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))

        _scsp_funcs._scsp_skipUnknowns(input, 8)
        
        skin_color = _scsp_funcs._scsp_4fuckingfloats2rgba(_scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input), 
                                                           _scsp_funcs._scsp_readFloat(input)) #RGBA
        
        _scsp_funcs._scsp_skipUnknowns(input, 8)
    
        skin_width      = _scsp_funcs._scsp_readInt(input)
        skin_height     = _scsp_funcs._scsp_readInt(input)

        _scsp_funcs._scsp_skipUnknowns(input, 72)
      
      
      elif (skin_mode == SP_ATTACHMENT_MESH): # mesh
        count_vertices = _scsp_funcs._scsp_readInt(input)
        ind2          = 0
        while (ind2 < count_vertices):
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),5))
          vertices4skin.append(tempo)
          ind2 = ind2 + 1
      
        skin_hull = _scsp_funcs._scsp_readInt(input)
        count_uvs = count_vertices
        
        #place for "wtf magic", don't ask me why i do that
        uvs4skin_ = []
        
        ind2      = 0
        while (ind2 < count_uvs): # first part for be last part
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),8))
          uvs4skin_.append(tempo)
          ind2 = ind2 + 1
          
        ind2      = 0
        while (ind2 < count_uvs): # last part for be first part (magic!)
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),8))
          uvs4skin.append(tempo)
          ind2 = ind2 + 1
          
        for tempo in uvs4skin_: uvs4skin.append(tempo) # add "first loaded part" to "uvs" list's end
      
        count_triangles = _scsp_funcs._scsp_readInt(input)
        ind2            = 0
        while (ind2 < count_triangles):
          tempo = _scsp_funcs._scsp_readInt(input)
          triangles4skin.append(tempo)
          ind2 = ind2 + 1
        
        skin_color = _scsp_funcs._scsp_4fuckingfloats2rgba(_scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input), 
                                                           _scsp_funcs._scsp_readFloat(input)) #RGBA
        _scsp_funcs._scsp_skipUnknowns(input, 48)
    
        skin_width      = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input)))
        skin_height     = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input)))
        
      elif (skin_mode == SP_ATTACHMENT_SKINNED_MESH): # skinnedmesh
        count_bones = _scsp_funcs._scsp_readInt(input)
        ind2        = 0
        while (ind2 < count_bones):
          tempo = _scsp_funcs._scsp_readInt(input)
          bones4skin.append(tempo)
          ind2 = ind2 + 1
      
        count_weights = _scsp_funcs._scsp_readInt(input)
        ind2          = 0
        while (ind2 < count_weights):
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),5))
          weights4skin.append(tempo)
          ind2 = ind2 + 1
        
        count_triangles = _scsp_funcs._scsp_readInt(input)
        ind2            = 0
        while (ind2 < count_triangles):
          tempo = _scsp_funcs._scsp_readInt(input)
          triangles4skin.append(tempo)
          ind2 = ind2 + 1
      
        count_uvs = _scsp_funcs._scsp_readInt(input)
        ind2      = 0
        
        while (ind2 < count_uvs):
          # два раза по float за один заход (а-ля: x, y)
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),8))
          uvs4skin.append(tempo)
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input),8))
          uvs4skin.append(tempo)
          ind2 = ind2 + 1
      
        skin_hull = _scsp_funcs._scsp_readInt(input)
        
        skin_color = _scsp_funcs._scsp_4fuckingfloats2rgba(_scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input),
                                                           _scsp_funcs._scsp_readFloat(input), 
                                                           _scsp_funcs._scsp_readFloat(input)) #RGBA
        _scsp_funcs._scsp_skipUnknowns(input, 48)
        
        skin_width      = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input)))
        skin_height     = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input)))
      elif (skin_mode == SP_ATTACHMENT_BOUNDING_BOX): # boundingbox
        # E7 2.1.27 BBOX layout (reverse-engineered 2026-05-21): the
        # skin_item_path_link2ref int read just above is repurposed as the
        # vertex count (number of FLOATS, i.e. 8 for a 4-vertex box). Followed
        # by `count` floats; no color, no pad. Validated against abigail.scsp
        # (output/model/) — 2 BBOX attachments, each count=8, parse stays in
        # sync with the next attachment's 5-int header.
        count_vertices = skin_item_path_link2ref
        ind2 = 0
        while (ind2 < count_vertices):
          tempo = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 5))
          vertices4skin.append(tempo)
          ind2 = ind2 + 1
        skin_item_path_link2ref = 0  # not a real path ref; null it so refstring lookup yields ""
      else:
        print(f"!!! Unknown skin_mode {skin_mode}; skipping skin")
        continue
    
    
      skin_attachment = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, skin_attachment_link2ref)
      skin_item_name  = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, skin_item_name_link2ref)
      skin_path_name  = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, skin_item_path_link2ref)

      # NOTE: the original Russian converter unconditionally cleared the slot
      # dict here (`= {}`) every time it processed a sub-record. For portrait
      # rigs (which have ~1 attachment per slot) that never mattered. For
      # combat rigs in output/model/ — which routinely carry 2-10 attachments
      # per slot for mesh-swap skill anims (e.g. head01/head02/head05 on the
      # `face` slot for damage/attack expressions) — every prior attachment on
      # the slot was wiped before the next one was added, leaving only the
      # LAST sub-record per slot in the JSON. Charlotte (c1009) parsed 162
      # sub-records but produced only 94 attachments (one per slot); skill
      # animations referencing `head05` etc. then resolved to "no attachment"
      # and the relevant body parts disappeared mid-skill.
      slot_key = slots[skin_slot]["name"]
      if slot_key not in skins[skin_name]:
        skins[skin_name][slot_key] = {}
      skins[skin_name][slot_key][skin_attachment] = {}
    
      if   (skin_mode == SP_ATTACHMENT_MESH):         skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["type"]   = "mesh"
      elif (skin_mode == SP_ATTACHMENT_SKINNED_MESH): skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["type"]   = "skinnedmesh"
      elif (skin_mode == SP_ATTACHMENT_BOUNDING_BOX): skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["type"]   = "boundingbox"

      skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["name"]   = skin_item_name
      skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["path"]   = skin_path_name
      
      if (skin_mode == SP_ATTACHMENT_REGION):
        if (skin_x != 0):         skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["x"]        = skin_x
        if (skin_y != 0):         skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["y"]        = skin_y
    
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["scaleX"]   = skin_scaleX
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["scaleY"]   = skin_scaleY
        
        if (skin_rotation != 0):  skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["rotation"] = skin_rotation
        
      elif (skin_mode == SP_ATTACHMENT_MESH): # mesh
        if (len(vertices4skin)): skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["vertices"]     = vertices4skin
        
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["hull"]      = skin_hull
        
        if (len(uvs4skin)):       skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["uvs"]       = uvs4skin
        if (len(triangles4skin)): skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["triangles"] = triangles4skin
      
      elif (skin_mode == SP_ATTACHMENT_SKINNED_MESH): # skinnedmesh
        if (len(bones4skin)):     skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["bones"]     = bones4skin
        if (len(weights4skin)):   skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["weights"]   = weights4skin
        if (len(triangles4skin)): skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["triangles"] = triangles4skin
        if (len(uvs4skin)):       skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["uvs"]       = uvs4skin

        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["hull"]   = skin_hull

      elif (skin_mode == SP_ATTACHMENT_BOUNDING_BOX): # boundingbox
        # Flat x,y vertex list; Spine 3.8 reads vertexCount + vertices and
        # treats it as unweighted when len(vertices) == vertexCount * 2.
        if (len(vertices4skin)):
          skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["vertexCount"] = len(vertices4skin) // 2
          skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["vertices"]    = vertices4skin

      if (skin_mode != SP_ATTACHMENT_BOUNDING_BOX):
        # boundingbox attachments have no texture region (no color/size)
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["color"]  = skin_color
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["width"]  = skin_width
        skins[skin_name][slots[skin_slot]["name"]][skin_attachment]["height"] = skin_height
    
      result4ffds.append({ "skin" : skin_name, "skin_slot" : slots[skin_slot]["name"], "skin_attachment" : skin_attachment})
      
      ind_sub = ind_sub + 1
    
    result.update(skins)
    ind = ind + 1
    
  return result, result4ffds
  

def _scsp_readEvents(input, refStrings_raw, count_events):
  # E7 2.1.27 events block (reverse-engineered 2026-05-22 on abigail.scsp).
  # Portrait rigs always have count_events=0; the block only appears on combat
  # rigs in output/model/. Layout: count_events × 16-byte records, each:
  #   [4 bytes] - sentinel (0 for first record, 0xFFFFFFFF=-1 for the rest —
  #               likely a "previous record terminator" marker, not payload)
  #   [4 bytes] - name_ref (uint, link2ref into refstrings)
  #   [4 bytes] - intValue
  #   [4 bytes] - floatValue (as float bits)
  # A trailing 4-byte separator (-1) sits between events and the animation
  # block; readAnimations() consumes it via its existing skip-4. Portrait
  # rigs have a 0 there instead (since no events precede it).
  result = {}
  for _ in range(count_events):
    _scsp_funcs._scsp_skipUnknowns(input, 4)             # sentinel
    name_link2ref = _scsp_funcs._scsp_readInt(input)
    int_value     = _scsp_funcs._scsp_readInt(input)
    float_bits    = _scsp_funcs._scsp_readInt(input)
    float_value   = struct.unpack("<f", struct.pack("<I", float_bits))[0]
    name          = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, name_link2ref)
    entry = {}
    if int_value   != 0:   entry["int"]   = int_value
    if float_value != 0.0: entry["float"] = round(float_value, 5)
    # Spine 3.8 events also support "string", but abigail's events all have
    # int=0, float=0 — no string field has surfaced. Add when we see one.
    result[name] = entry
  return result


def _scsp_isPlausibleAnimHeader(input, pos, refStrings_raw, pos4RefStrings, size4RefStrings, spine_hash, exclude_names, bone_slot_names=None):
  # 2026-05-22: combat-rig RE helper. Each animation in a combat rig is
  # followed by a variable-size trailer (~681 bytes minimum for single-frame
  # poses, up to ~110KB for complex animations) carrying draw-order /
  # event-timeline data that the existing reader doesn't model. We skip it
  # by scanning forward for the next plausible animation header.
  #
  # Header layout:  name_link2ref(4) + duration_float(4) + items_count(4)
  # An accepted header must: (1) name_ref point at a string start in
  # refstrings, (2) name pass length/charset filter and not be the spine
  # hash or a name we already used, (3) duration be exactly 0.0 (the
  # single-frame poses appear/attacked_damage/flying_damage) OR a normal
  # float in [0.05, 60], (4) items_count be in [100, 50000].
  if pos < 0 or pos + 12 > pos4RefStrings: return False, None

  input.seek(pos)
  nref = struct.unpack('<I', input.read(4))[0]
  if nref >= size4RefStrings: return False, None
  if nref != 0 and refStrings_raw[nref - 1] != 0: return False, None

  name = refStrings_raw[nref:].split(b'\x00', 1)[0].decode('utf-8', 'replace')
  if not name or len(name) < 3 or len(name) > 30: return False, None
  if name == spine_hash: return False, None
  if name in exclude_names: return False, None
  # Reject candidates whose name is a known bone or slot name. These are the
  # dominant false-positive class at the animation boundary: the trailer that
  # follows an animation's timeline items contains ref-offsets that frequently
  # land on a bone/slot ref (e.g. 'pelvis_r') which otherwise passes every
  # format check below, derailing the scan onto a bone and crashing the
  # subsequent item parse. Animation names are disjoint from bone/slot names.
  if bone_slot_names and name in bone_slot_names: return False, None
  # Animation names in E7 combat rigs always start with a lowercase letter
  # (appear, attacked, b_idle, camping, idle, knock_down, skill1, ...). Slot
  # and bone names commonly start with digits (1_hair_sr, 6_ac_sdw_r) or
  # symbols, so this excludes the largest false-positive class.
  c0 = name[0]
  if not ('a' <= c0 <= 'z'): return False, None
  # Animation names contain only alphanumerics + underscore. Slot names use
  # slashes/dots/spaces — exclude those.
  for c in name:
    if not (c.isalnum() or c == '_'): return False, None

  dur_bits = struct.unpack('<I', input.read(4))[0]
  if dur_bits != 0:
    exp = (dur_bits >> 23) & 0xff
    if exp == 0: return False, None  # denormal
    dur = struct.unpack('<f', struct.pack('<I', dur_bits))[0]
    if not (0.05 <= dur <= 60): return False, None

  items_count = struct.unpack('<I', input.read(4))[0]
  if items_count < 100 or items_count > 50000: return False, None

  return True, name


# max_search defaults to the whole remaining data region (end_scan clamps to
# pos4RefStrings-12 anyway). The old 300000 cap silently truncated rigs whose
# next animation header sat past a >300 KB block — ray_m (c2090) stopped at 5/18
# anims, achates_m2 (c6017) at 6/18. Behaviour is unchanged for the ~140 working
# rigs: the scan returns the FIRST plausible header from scan_start, so when the
# true header is near (the normal case) the result is identical; the wider window
# only matters when the true header is farther away.
def _scsp_findNextAnimHeader(input, start_pos, pos4RefStrings, size4RefStrings, refStrings_raw, spine_hash, exclude_names, prev_anim_end=0, max_search=16_000_000, backward_pad=64, bone_slot_names=None):
  # Scan byte-by-byte — combat-rig animation headers are NOT 4-byte aligned
  # (e.g. abigail's 'attacked' lives at 0x55395, alignment 1). We also allow
  # a small backward look-back (up to backward_pad bytes) to handle item
  # readers that over-consume by a handful of bytes; exclude_names prevents
  # us from re-matching the animation we just finished.
  scan_start = max(prev_anim_end, start_pos - backward_pad)
  end_scan = min(start_pos + max_search, pos4RefStrings - 12)
  off = scan_start
  while off <= end_scan:
    ok, name = _scsp_isPlausibleAnimHeader(input, off, refStrings_raw, pos4RefStrings, size4RefStrings, spine_hash, exclude_names, bone_slot_names)
    if ok:
      input.seek(off)
      return off, name
    off += 1
  return None, None


def _scsp_readAnimations(input, refStrings_raw, pos4RefStrings, size4RefStrings, bones, slots, skins4ffds, count_animations, skins=None): #, count_animations_slots, count_animations_bones):
  result          = {}
  animation_ind   = 0
  # Trailer-skip support: spine hash is refstrings[0]; exclude_names grows
  # as each animation is parsed so scan-forward never re-matches a name.
  spine_hash      = refStrings_raw[0:].split(b'\x00', 1)[0].decode('utf-8', 'replace')
  exclude_names   = set()
  # Names of every bone and slot — used to reject false animation-header
  # matches during trailer skip (a bone ref like 'pelvis_r' otherwise passes
  # the header format check and derails parsing). See _scsp_isPlausibleAnimHeader.
  bone_slot_names = {b["name"] for b in bones if "name" in b} | {s["name"] for s in slots if "name" in s}
  # Also reject skin-attachment names. The trailer that follows an animation's
  # timeline items contains ref-offsets that frequently land on an attachment
  # ref (e.g. 'leg_right_band3' on achates_s01, 'hand_10b' on byblis) which
  # otherwise passes the lowercase/alnum header filter, derails the scan onto
  # an attachment, and crashes the item parse with a struct buffer overrun.
  # Animation names are disjoint from attachment names. Harvest the placeholder
  # keys plus each attachment's region name/path.
  if skins:
    for _skin in skins.values():
      for _slot_atts in _skin.values():
        for _att_name, _att in _slot_atts.items():
          if _att_name: bone_slot_names.add(_att_name)
          if isinstance(_att, dict):
            for _k in ("name", "path"):
              _v = _att.get(_k)
              if _v: bone_slot_names.add(_v)

  while (animation_ind < count_animations) and (input.tell() < pos4RefStrings):

    if (animation_ind == 0):
      _scsp_funcs._scsp_skipUnknowns(input, 4)
      animation_new = True
    elif (anim_items_ind == anim_items_count):
      # End of prior animation's items. Scan forward to next header. Capture
      # the bytes between cur_pos and next_pos as the previous animation's
      # trailer — they contain the per-frame slot-permutation (drawOrder)
      # data. Stored under '_e7_trailer_b64' on the previous animation; the
      # 2.1.27 post-processor decodes it into a Spine drawOrder timeline.
      cur_pos = input.tell()
      next_pos, _ = _scsp_findNextAnimHeader(input, cur_pos, pos4RefStrings, size4RefStrings, refStrings_raw, spine_hash, exclude_names, prev_anim_end=prev_anim_items_start, bone_slot_names=bone_slot_names)
      if next_pos is None:
        break
      try:
        if next_pos > cur_pos and animation_name and animation_name in animations:
          input.seek(cur_pos)
          _e7_trailer_bytes = input.read(next_pos - cur_pos)
          import base64
          animations[animation_name]["_e7_trailer_b64"] = base64.b64encode(_e7_trailer_bytes).decode('ascii')
          input.seek(next_pos)
      except Exception as _e7_e:
        pass
      animation_new = True
    else:
      animation_new = False

    if animation_new:
      anim_items_ind          = 0
      animation_ind           = animation_ind + 1
      hdr_pos                 = input.tell()
      prev_anim_items_start   = hdr_pos + 12  # used as backward-scan floor for the next trailer-skip
      animation_name_link2ref = _scsp_funcs._scsp_readInt(input)
      animation_name          = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, animation_name_link2ref)
      animations              = { animation_name : {}}
      exclude_names.add(animation_name)

      _scsp_funcs._scsp_skipUnknowns(input, 4)
      anim_items_count        = _scsp_funcs._scsp_readInt(input)
      # Sanity check: if items_count is unreasonably large (>100000), file is probably corrupted
      if anim_items_count > 100000:
        print(f"!!! Unreasonable anim_items_count: {anim_items_count} for {animation_name!r}; stopping animation parsing")
        break
      
    else:
      animation_mode       = _scsp_funcs._scsp_readInt(input)

      if (animation_mode >= 65534):
        print (f"!!! animation_mode: {format(animation_mode & 0xFFFF, '08x')} at pos={input.tell()-4} anim={animation_name!r} item={anim_items_ind}/{anim_items_count}; skipping")
        # Skip this corrupted animation timeline and continue
        anim_items_ind = anim_items_ind + 1
        continue
      else:
        
        if (animation_mode == SP_TIMELINE_SCALE): # bone/scale
          animation_slot = _scsp_funcs._scsp_readInt(input)
          entry_count    = _scsp_funcs._scsp_readInt(input) // 3
          entry_scales   = []
      
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив
      
            entry_time    = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_scale_x = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_scale_y = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
     
            entry = {"time" : entry_time}
            if (entry_scale_x != 1): entry["x"] = entry_scale_x
            if (entry_scale_y != 1): entry["y"] = entry_scale_y
            
            entry_scales.append(entry)
            entry_ind = entry_ind + 1
            
          animation_mode_curve = _scsp_funcs._scsp_readShortInt(input)
          if (animation_mode_curve < 65534):
            entry_ind   = 0
            while (entry_ind < (entry_count - 1)): # загружаем массив
      
              animation_mode_curve = _scsp_funcs._scsp_readByte(input)
              
              if (animation_mode_curve == SP_CURVE_STEPPED):
                entry_scales[entry_ind]["curve"] = "stepped"
              elif (animation_mode_curve == SP_CURVE_BEZIER):
                _scsp_funcs._scsp_skipUnknowns(input, 4) # skip... time?
              
                entry_scales[entry_ind]["curve"] = [_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))] # 4 floats
              
              elif (animation_mode_curve != 0):
                print(f"!!! Unknown curve type {animation_mode_curve}; continuing")

              entry_ind = entry_ind + 1

        elif (animation_mode == SP_TIMELINE_ROTATE): # bone/rotate
          animation_slot = _scsp_funcs._scsp_readInt(input)
          entry_count    = _scsp_funcs._scsp_readInt(input) // 2
          entry_rotates  = []
      
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив
      
            entry_time   = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_rotate = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
     
            entry = {"time" : entry_time}
            if (entry_rotate != 0): entry["angle"] = entry_rotate
            
            entry_rotates.append(entry)
            entry_ind = entry_ind + 1
            
          animation_mode_curve = _scsp_funcs._scsp_readShortInt(input)
          if (animation_mode_curve < 65534):
            entry_ind   = 0
            while (entry_ind < (entry_count - 1)): # загружаем массив
      
              animation_mode_curve = _scsp_funcs._scsp_readByte(input)
              
              if (animation_mode_curve == SP_CURVE_STEPPED):
                entry_rotates[entry_ind]["curve"] = "stepped"
              elif (animation_mode_curve == SP_CURVE_BEZIER):
                _scsp_funcs._scsp_skipUnknowns(input, 4) # skip... time?
              
                entry_rotates[entry_ind]["curve"] = [_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                     _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                     _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                     _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))] # 4 floats
              
              elif (animation_mode_curve != 0):
                print(f"!!! Unknown curve type {animation_mode_curve}; continuing")

              entry_ind = entry_ind + 1

        elif (animation_mode == SP_TIMELINE_TRANSLATE): # bone/translate
          animation_slot   = _scsp_funcs._scsp_readInt(input)
          entry_count      = _scsp_funcs._scsp_readInt(input) // 3
          entry_translates = []
      
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив
      
            entry_time        = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_translate_x = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_translate_y = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
     
            entry = {"time" : entry_time}
            if (entry_translate_x != 0): entry["x"] = entry_translate_x
            if (entry_translate_y != 0): entry["y"] = entry_translate_y
            
            entry_translates.append(entry)
            entry_ind = entry_ind + 1
            
          animation_mode_curve = _scsp_funcs._scsp_readShortInt(input)
          if (animation_mode_curve < 65534):
            entry_ind   = 0
            while (entry_ind < (entry_count - 1)): # загружаем массив
      
              animation_mode_curve = _scsp_funcs._scsp_readByte(input)
              
              if (animation_mode_curve == SP_CURVE_STEPPED):
                entry_translates[entry_ind]["curve"] = "stepped"
              elif (animation_mode_curve == SP_CURVE_BEZIER):
                _scsp_funcs._scsp_skipUnknowns(input, 4) # skip... time?
              
                entry_translates[entry_ind]["curve"] = [_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                        _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                        _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                        _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))] # 4 floats
              elif (animation_mode_curve != 0):
                print(f"!!! Unknown curve type {animation_mode_curve}; continuing")

              entry_ind = entry_ind + 1

        elif (animation_mode == SP_TIMELINE_COLOR): # skin/color
          animation_slot = _scsp_funcs._scsp_readInt(input)
          entry_count    = _scsp_funcs._scsp_readInt(input) // 5
          entry_colors   = []
      
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив
      
            entry_time  = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_color = _scsp_funcs._scsp_4fuckingfloats2rgba(_scsp_funcs._scsp_readFloat(input),
                                                                _scsp_funcs._scsp_readFloat(input),
                                                                _scsp_funcs._scsp_readFloat(input), 
                                                                _scsp_funcs._scsp_readFloat(input)) #RGBA
     
            entry_colors.append({"color" : entry_color, "time" : entry_time})
            entry_ind = entry_ind + 1
            
          animation_mode_curve = _scsp_funcs._scsp_readShortInt(input)
          if (animation_mode_curve < 65534):
            entry_ind   = 0
            while (entry_ind < (entry_count - 1)): # загружаем массив
      
              animation_mode_curve = _scsp_funcs._scsp_readByte(input)
              
              if (animation_mode_curve == SP_CURVE_STEPPED):
                entry_colors[entry_ind]["curve"] = "stepped"
              elif (animation_mode_curve == SP_CURVE_BEZIER):
                _scsp_funcs._scsp_skipUnknowns(input, 4) # skip... time?
              
                entry_colors[entry_ind]["curve"] = [_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                                    _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))] # 4 floats
              elif (animation_mode_curve != 0):
                print(f"!!! Unknown curve type {animation_mode_curve}; continuing")

              entry_ind = entry_ind + 1

        elif (animation_mode == SP_TIMELINE_ATTACHMENT): # skin/attachment
          animation_slot = _scsp_funcs._scsp_readInt(input)
          entry_count    = _scsp_funcs._scsp_readInt(input)
          attachments    = []
          entry_names    = []
          entry_times    = []
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив времени
            entry_time = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_times.append(entry_time)
            entry_ind  = entry_ind + 1

          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив наименований
            entry_name_link2ref = _scsp_funcs._scsp_readInt(input)
            # Sentinel for "hide attachment" is uint32 0xFFFFFFFF, NOT 65535.
            # Combat rigs have refstring tables in the 100-200 KB range and
            # most animation-attachment refs live past 65535 — the old check
            # collapsed every real attachment to "" (empty string), which
            # spine-player interprets as "no attachment" and clears the slot.
            # Net effect: skill animations rendered as shadow-only.
            if (entry_name_link2ref != 0xFFFFFFFF):
              entry_name = _scsp_funcs._scsp_extract_from_RefStrings(refStrings_raw, entry_name_link2ref)
            else:
              entry_name = None  # Spine 3.8 wants null, not "", for hidden frames
            entry_names.append(entry_name)
            entry_ind  = entry_ind + 1
        
          entry_ind   = 0
          while (entry_ind < entry_count): # соединяем
            attachments.append({"name" : entry_names[entry_ind], "time" : entry_times[entry_ind]})
            entry_ind  = entry_ind + 1
      
        elif (animation_mode == 5): # EVENT timeline (Ghidra: SCSLoader readAnimation case 5)
          # The converter historically mislabeled mode 5 as FLIPX and under-read it.
          # Real layout (FUN_14032bc30 case 5): u32 count; count × f32 times;
          # count × { u32, u32, u32 string-ref(0xFFFFFFFF=null), u16 event-def idx }.
          # Events don't drive rendering; we read the exact stride so the item
          # stream stays aligned (the old misread desynced everything after it).
          entry_count = _scsp_funcs._scsp_readInt(input)
          for _e7_i in range(entry_count):
            _scsp_funcs._scsp_readFloat(input)        # time
          for _e7_i in range(entry_count):
            _scsp_funcs._scsp_readInt(input)          # value a (int/float bits)
            _scsp_funcs._scsp_readInt(input)          # value b
            _scsp_funcs._scsp_readInt(input)          # string ref
            _scsp_funcs._scsp_readShortInt(input)     # event-def index (u16)

        elif (animation_mode == 6): # DRAWORDER timeline (Ghidra: SCSLoader readAnimation case 6)
          # The converter historically mislabeled mode 6 as FLIPY, which both lost
          # the drawOrder data AND desynced the stream (the source of the old
          # "phantom trailer" and the ~13 trailer-skip crashes). Real layout
          # (FUN_14032bc30 case 6): u32 vertCount (== slot count); u32 frameCount;
          # frameCount × f32 times; per frame: u8 flag, then if flag != 0,
          # vertCount × u32 (a full slot permutation in target draw order).
          do_vert_count  = _scsp_funcs._scsp_readInt(input)
          do_frame_count = _scsp_funcs._scsp_readInt(input)
          do_times       = [round(_scsp_funcs._scsp_readFloat(input), 4) for _e7_i in range(do_frame_count)]
          do_frames      = []
          for _e7_fi in range(do_frame_count):
            _e7_flag = _scsp_funcs._scsp_readByte(input)
            if _e7_flag != 0:
              _e7_order = [_scsp_funcs._scsp_readInt(input) for _e7_j in range(do_vert_count)]
            else:
              _e7_order = None
            do_frames.append({"time": do_times[_e7_fi], "order": _e7_order})
          animations[animation_name]["_e7_draworder"] = {"slotCount": do_vert_count, "frames": do_frames}

        elif (animation_mode == SP_TIMELINE_FFD): # skin/ffd
          entry_count    = _scsp_funcs._scsp_readInt(input)
          entry_ffds     = []
          entry_curves   = []
          entry_vertices = []
          entry_times    = []
          
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив времени
            entry_time = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            entry_times.append(entry_time)
            entry_ind  = entry_ind + 1
          
          _scsp_funcs._scsp_skipUnknowns(input, 4)

          frames_count   = _scsp_funcs._scsp_readInt(input)
          
          entry_ind   = 0
          while (entry_ind < entry_count): # загружаем массив
            entry     = []
            frame_ind = 0
            while (frame_ind < frames_count):
              entry.append(_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 8)))
              frame_ind = frame_ind + 1
                        
            entry_vertices.append(entry)
            
            entry_ind = entry_ind + 1
            
          animation_mode_curve = _scsp_funcs._scsp_readShortInt(input)
          if (animation_mode_curve < 65534):
            entry_ind  = 0
            while (entry_ind < (entry_count - 1)): # загружаем массив
              entry                = {}
              animation_mode_curve = _scsp_funcs._scsp_readByte(input)
              
              if (animation_mode_curve == SP_CURVE_STEPPED):
                entry["curve"] = "stepped"
              elif (animation_mode_curve == SP_CURVE_BEZIER):
                _scsp_funcs._scsp_skipUnknowns(input, 4) # skip... time?
              
                entry["curve"] = [_scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                  _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                  _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4)), 
                                  _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))] # 4 floats
              elif (animation_mode_curve != 0):
                print(f"!!! Unknown curve type {animation_mode_curve}; continuing")

              entry_curves.append(entry)
              entry_ind = entry_ind + 1
              
          entry_curves.append({})
              
          entry_ind = 0
          while (entry_ind < entry_count):
            entry_ffd = {}
            
            if (entry_ind < len(entry_curves)):
              if ("curve" in entry_curves[entry_ind]): 
                entry_ffd["curve"] = entry_curves[entry_ind]["curve"]
            
            entry_ffd["time"]     = entry_times[entry_ind]
            
            vertices_ind          = 0
            b_vertices_zeros_only = True
            while (vertices_ind < len(entry_vertices[entry_ind])):
              if (entry_vertices[entry_ind][vertices_ind] != 0): b_vertices_zeros_only = False
              vertices_ind = vertices_ind + 1
              
            if (not b_vertices_zeros_only): entry_ffd["vertices"] = entry_vertices[entry_ind]
            
            entry_ffds.append(entry_ffd)
            entry_ind = entry_ind + 1
          
          skin4ffd_id          = _scsp_funcs._scsp_readInt(input)
          animation_skin       = skins4ffds[skin4ffd_id]["skin"]
          animation_slot       = skins4ffds[skin4ffd_id]["skin_slot"]
          animation_attachment = skins4ffds[skin4ffd_id]["skin_attachment"]

        elif (animation_mode == 9) or (animation_mode == 10):
          # E7-specific bone-mix-to-setup timeline (combat rigs only).
          # Reverse-engineered 2026-05-22 (byte layout) and 2026-05-23 (semantics)
          # from abigail.scsp. Layout after the mode dword:
          #   idx(4) + sub_type(4) + raw_count(4) + count*frame(8 each)
          # frame = (time:float, mix:float) — count = raw_count // 2.
          # Semantics: idx is a BONE INDEX. mix in [0,1] is a per-frame mix toward
          # setup pose for that bone (mix=0 → full animation; mix=1 → full setup).
          # Confirmed visually on c1144 idle 2026-05-23: head/center/leg bones with
          # mode 9 mix=1 in idle were rendering at their (non-zero) animated rotate/
          # translate deltas, producing the user-reported "head offset" and splayed-
          # legs symptoms. Clearing those bones' rotate/translate per the mix
          # restored the correct standing pose. See post_process_2_1_27 for the
          # actual application — the reader just captures the raw record here.
          # No public Spine 3.8 timeline maps onto this exactly (transform
          # constraints would need a target bone we don't have), so we bake the
          # mix into the bone's rotate/translate/scale timeline values directly:
          #   new_value(t) = (1 - mix(t)) * animation_value(t) + mix(t) * setup_value
          # where setup_value is 0 for rotate/translate (deltas) and 1 for scale.
          e7_idx       = _scsp_funcs._scsp_readInt(input)
          e7_sub_type  = _scsp_funcs._scsp_readInt(input)
          e7_raw_count = _scsp_funcs._scsp_readInt(input)
          e7_count     = e7_raw_count // 2
          e7_frames    = []
          for _i in range(e7_count):
            e7_t = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            e7_v = _scsp_funcs._scsp_remove_float_zero(round(_scsp_funcs._scsp_readFloat(input), 4))
            e7_frames.append({"time": e7_t, "mix": e7_v})
          animations[animation_name].setdefault("_e7_mix_records", []).append({
            "mode":     animation_mode,
            "idx":      e7_idx,
            "sub_type": e7_sub_type,
            "frames":   e7_frames,
          })

        if ((animation_mode == SP_TIMELINE_SCALE) or (animation_mode == SP_TIMELINE_ROTATE) or (animation_mode == SP_TIMELINE_TRANSLATE)): # bones
          if ("bones" not in animations[animation_name]):
            animations[animation_name]["bones"] = {}
          # Bounds check: skip malformed animation data with invalid bone indices
          if animation_slot < 0 or animation_slot >= len(bones):
            continue
          if (bones[animation_slot]["name"] not in animations[animation_name]["bones"]):
            animations[animation_name]["bones"][bones[animation_slot]["name"]] = {}

          if (animation_mode == SP_TIMELINE_SCALE):  # scale
            animations[animation_name]["bones"][bones[animation_slot]["name"]]["scale"] = entry_scales
          elif (animation_mode == SP_TIMELINE_ROTATE): # rotate
            animations[animation_name]["bones"][bones[animation_slot]["name"]]["rotate"] = entry_rotates
          elif (animation_mode == SP_TIMELINE_TRANSLATE): # translate
            animations[animation_name]["bones"][bones[animation_slot]["name"]]["translate"] = entry_translates

        elif ((animation_mode == SP_TIMELINE_COLOR) or (animation_mode == SP_TIMELINE_ATTACHMENT)): # slots
          if ("slots" not in animations[animation_name]):
            animations[animation_name]["slots"] = {}
          # Bounds check: skip malformed animation data with invalid slot indices
          if animation_slot < 0 or animation_slot >= len(slots):
            continue
          if (slots[animation_slot]["name"] not in animations[animation_name]["slots"]):
            animations[animation_name]["slots"][slots[animation_slot]["name"]] = {}
        
          if (animation_mode == SP_TIMELINE_COLOR): # color
            animations[animation_name]["slots"][slots[animation_slot]["name"]]["color"] = entry_colors
          elif (animation_mode == SP_TIMELINE_ATTACHMENT): # attachment
            animations[animation_name]["slots"][slots[animation_slot]["name"]]["attachment"] = attachments
          
        elif (animation_mode == SP_TIMELINE_FFD): # ffd
          if ("ffd" not in animations[animation_name]):
            animations[animation_name]["ffd"] = {}
          if (animation_skin not in animations[animation_name]["ffd"]):
            animations[animation_name]["ffd"][animation_skin] = {}
            
          if (animation_slot not in animations[animation_name]["ffd"][animation_skin]):
            animations[animation_name]["ffd"][animation_skin][animation_slot] = { animation_attachment : [] }
            
          animations[animation_name]["ffd"][animation_skin][animation_slot][animation_attachment] = entry_ffds

        elif (animation_mode == 5) or (animation_mode == 6):
          # EVENT (5) / DRAWORDER (6) fully read + stored in the read section above.
          pass

        elif (animation_mode == 9) or (animation_mode == 10):
          # Constraint timeline already consumed above; no JSON to emit.
          pass

        else:
          print(f"!!! unhandled mode={animation_mode} in {animation_name!r} item {anim_items_ind} at pos={input.tell()-4}; skipping")
          # Skip this corrupted animation timeline
          anim_items_ind = anim_items_ind + 1
          continue

        anim_items_ind = anim_items_ind + 1
    
    result.update(animations)
    
  return result
  

# основная функция модуля
def ConvertSCSPtoJSON(filename4scsp, argv_e7herder):
  # заново подключаемся к файлу и снова загружаем справочник
  mfilesize   = os.path.getsize(filename4scsp)
  if platform.system() == 'Windows':
    mfd           = os.open(filename4scsp, os.O_RDONLY | os.O_BINARY)
    mfile         = mmap.mmap(mfd, 0, access=mmap.ACCESS_READ)
  else:
    mfd           = os.open(filename4scsp, os.O_RDONLY)
    mfile         = mmap.mmap(mfd, 0, prot=mmap.PROT_READ)

  pos4RefStrings  = _scsp_funcs._scsp_readInt(mfile) + 8 # объем в байтах всех блоков файла, за исключением блока служебных меток. 
                                                         # прибавляем 8 байт, чтобы получить фактический адрес блока со списком служебных меток
  size4RefStrings = _scsp_funcs._scsp_readInt(mfile)     # общий размер в байтах, занятый списком служебных меток (метки разделяются h00)
  
  refStrings_raw = _scsp_funcs._scsp_readRefStrings_raw(mfile, pos4RefStrings, size4RefStrings)
  refStrings     = _scsp_funcs._scsp_readRefStrings(mfile, pos4RefStrings, size4RefStrings)

  # Detect new-style header: bytes [8:12] == b"scsp" magic.
  # Old format: counts at [8..32], width/height at [72..80], bones at offset 88.
  # New format: "scsp" magic at [8], counts at [44..72], width/height at [20..28], bones at offset 116.
  mfile.seek(8)
  is_new_format = (mfile.read(4) == b"scsp")

  if is_new_format:
    mfile.seek(44)
    count_bones      = _scsp_funcs._scsp_readInt(mfile)  # [44:48]
    count_ik         = _scsp_funcs._scsp_readInt(mfile)  # [48:52]
    count_slots      = _scsp_funcs._scsp_readInt(mfile)  # [52:56]
    count_skins      = _scsp_funcs._scsp_readInt(mfile)  # [56:60]
    count_events     = _scsp_funcs._scsp_readInt(mfile)  # [60:64]
    _                = _scsp_funcs._scsp_readInt(mfile)  # [64:68] unknown extra field
    count_animations = _scsp_funcs._scsp_readInt(mfile)  # [68:72]
    mfile.seek(20)
    width  = round(_scsp_funcs._scsp_readFloat(mfile), 2)  # [20:24]
    height = round(_scsp_funcs._scsp_readFloat(mfile), 2)  # [24:28]
    bones_start = 116
  else:
    mfile.seek(8)
    count_bones      = _scsp_funcs._scsp_readInt(mfile)
    count_ik         = _scsp_funcs._scsp_readInt(mfile)
    count_slots      = _scsp_funcs._scsp_readInt(mfile)
    count_skins      = _scsp_funcs._scsp_readInt(mfile)
    count_events     = _scsp_funcs._scsp_readInt(mfile)
    count_animations = _scsp_funcs._scsp_readInt(mfile)
    mfile.seek(72)
    width  = round(_scsp_funcs._scsp_readFloat(mfile), 2)
    height = round(_scsp_funcs._scsp_readFloat(mfile), 2)
    bones_start = 88
  
  # инициализируем будущий json
  prep4json             = {"skeleton": {}, "bones": [], "slots": [], "skins": {}, "events": {}, "animations": {}}
  # заполняем skeleton
  prep4json["skeleton"] = {"hash"   : refStrings[0].decode("utf-8", "ignore"), "spine" : refStrings[1].decode("utf-8", "ignore"), 
                           "x"      : 0, "y" : 0,
                           "width"  : width, "height" : height,
                           "images" : "",
                           "audio"  : ""
                           }
  
  # загружаем массивы bones, slots, skins, animations
  bones             = _scsp_readBones     (mfile, refStrings_raw, count_bones, bones_start)
  slots             = _scsp_readSlots     (mfile, refStrings_raw, bones, count_slots)
  skins, skins4ffds = _scsp_readSkins     (mfile, refStrings_raw, bones, slots, count_skins)
  events            = _scsp_readEvents    (mfile, refStrings_raw, count_events)
  animations        = _scsp_readAnimations(mfile, refStrings_raw, pos4RefStrings, size4RefStrings, bones, slots, skins4ffds, count_animations, skins)
  
  # вписываем полученные массивы в skeleton
  prep4json["bones"]      = bones
  prep4json["slots"]      = slots
  
  if argv_e7herder: # делаем дополнительную сортировку данных для удобства сравнения с json-файлами из e7herder dump
    prep4json["skins"]      = _scsp_funcs.sort_skins_json (skins)
    prep4json["animations"] = _scsp_funcs.sort_animations_json (animations)
  else:
    prep4json["skins"]      = skins
    prep4json["animations"] = animations
  if events:
    prep4json["events"]     = events
  else:
    # Spine 3.8 accepts JSONs without an `events` key when there are no events
    # to declare; remove the empty placeholder so portrait outputs stay byte-
    # identical to the historical converter output.
    prep4json.pop("events", None)

  # отключаемся от файла  
  mfile.close()
  os.close(mfd)
  
  return prep4json # выплёвываем полученный json
