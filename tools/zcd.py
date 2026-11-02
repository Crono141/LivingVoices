import struct,subprocess,sys,collections,json,zlib
U=sys.argv[1]
def rng(a,b): return subprocess.run(['curl','-sL','-r',f'{a}-{b}',U],capture_output=True).stdout
size=int(subprocess.run(['curl','-sIL',U],capture_output=True,text=True).stdout.lower().split('content-length:')[-1].split()[0])
t=rng(size-65536,size-1)
i=t.rfind(b'PK\x05\x06'); n,cs,co=struct.unpack('<HII',t[i+10:i+20])
j=t.rfind(b'PK\x06\x07')
if co==0xffffffff or j>=0:
  k=t.rfind(b'PK\x06\x06'); n,cs,co=struct.unpack('<QQQ',t[k+32:k+56])
d=rng(co,co+cs-1);p=0;ents={}
while p<len(d) and d[p:p+4]==b'PK\x01\x02':
  meth=struct.unpack('<H',d[p+10:p+12])[0]
  csz,usz=struct.unpack('<II',d[p+20:p+28]); nl,el,cl=struct.unpack('<HHH',d[p+28:p+34]); off=struct.unpack('<I',d[p+42:p+46])[0]
  name=d[p+46:p+46+nl].decode('utf8','replace'); ents[name]=(meth,csz,usz,off); p+=46+nl+el+cl
json.dump(ents,open(sys.argv[2],'w'))
c=collections.Counter(); s=collections.Counter()
for nm,(m,cz,u,o) in ents.items():
  k='/'.join(nm.split('/')[:-1]); c[k]+=1; s[k]+=u
print(size,len(ents))
for k in sorted(c): print(' ',k,c[k],round(s[k]/1e6),'MB')
for nm,(m,cz,u,o) in ents.items():
  if not (nm.endswith('.mp3') or nm.endswith('.ogg') or nm.endswith('/')): print('  F',nm,u)
q=[x.split('/')[-1] for x in ents if '/quests/' in x]
print('  accept',sum('-accept' in x for x in q),'complete',sum('-complete' in x for x in q),'progress',sum('-progress' in x for x in q),'uniq quests',len({x.split('-')[-2] for x in q if '-' in x}))
print('  sample',q[:3],q[-3:])
