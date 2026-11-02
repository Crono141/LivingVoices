import json,struct,subprocess,sys,zlib
U,J,name,out=sys.argv[1:5]
ents=json.load(open(J)); m,csz,usz,off=ents[name]
b=subprocess.run(['curl','-sL','-r',f'{off}-{off+csz+700}',U],capture_output=True).stdout
nl,el=struct.unpack('<HH',b[26:30]); d=b[30+nl+el:30+nl+el+csz]
if m==8: d=zlib.decompressobj(-15).decompress(d)
open(out,'wb').write(d)
