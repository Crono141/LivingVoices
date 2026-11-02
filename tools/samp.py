import sys; sys.argv=['x']
exec(open('reuse.py').read().split("if __name__ == '__main__' and len(sys.argv) > 1")[0])
xs=[]
for k,d in evals.items():
  for pk,(tier,r,fn,cz,dur,words) in d.items():
    if 'differs' in tier and r is not None: xs.append((r,k,pk,tier))
xs.sort()
print(len(xs), collections.Counter(p for _,_,p,_ in xs))
import random; random.seed(3)
low=[x for x in xs if x[0]<0.8]; print('ratio<0.8:',len(low), collections.Counter(p for _,_,p,_ in low))
for r,k,pk,tier in random.sample(low,6):
  q,kind,v=k; src = CT.get((q,kind)) if pk in ('spoken','mrthinger') else (NEW.get((q,kind)) or [None])[0]
  print('----',k,pk,tier,round(r,2),ours[str(q)]['title']); print(' OURS:',ws(our_clips[k][0])[:260]); print(' SRC :',ws(src or '')[:260])
print('#### title differs')
for k,d in evals.items():
  for pk,(tier,*_) in d.items():
    if tier.startswith('id_title_differs'): print(k,pk,'ours:',ours[str(k[0])]['title'],'| pack:',LK[pk][(k[0],k[1])]['titles'])
# progress uniqueness
pt=collections.Counter(ws(t) for (q,kind,v),(t,w) in our_clips.items() if kind=='progress')
print('progress clips',sum(pt.values()),'distinct texts',len(pt), 'top', pt.most_common(3))
rem=[r for r in csv.reader(open('to_generate.csv'))][1:]
print('remaining quests with accept missing',len({r[0] for r in rem if r[1]=='accept'}))
