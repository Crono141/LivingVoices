import sys; sys.argv=['x']
exec(open('reuse.py').read().split("if __name__ == '__main__' and len(sys.argv) > 1")[0].split("plan, togen = [], []")[0])
import numpy as np
for pk in ['carevass_TBC','carevass_WoTLK','carevass_VanillaExtra','mrthinger']:
  for tp in ['fp_exact','newentry_exact','id_title','id_only','proxy_exact','proxy_differs','fp_differs']:
    r=[d[pk][4]/(MED[pk]*d[pk][5]+1) for k,d in evals.items() if pk in d and d[pk][0].startswith(tp) and d[pk][4] and d[pk][5]>=5]
    if len(r)>5: print(pk,tp,len(r),np.percentile(r,[0.5,1,2,5,50,95,98,99,99.5]).round(2))
