"""Regression fixture: the decision hook of the reference build (Convergence 3.0.2 + Nightreign Movement
1.0.0-beta.16 + Suncatcher 1.4.1), comment text included, so the build can be compared byte for byte.
Independent of the A/B orientation (it patches staging paths). Copy to <W>/hooks/post_merge.py.

usage (by build.py): python post_merge.py <staging folder> <workspace folder>
  action/script/c0000.hks          merged with encoding_from = Suncatcher: UTF-8 BOM + CRLF
  action/script/nrm-extension.hks  copied from NRM: LF
"""
import sys
from pathlib import Path

staging = Path(sys.argv[1])


def patch(rel, old, new):
    p = staging / rel
    data = p.read_bytes()
    n = data.count(old)
    if n != 1:
        sys.exit(f'{rel}: anchor found {n} times, expected exactly once: {old[:80]!r}')
    p.write_bytes(data.replace(old, new))
    print(f'patched {rel}')


# Decision 1.1: L3 belongs to NRM's sprint toggle; Suncatcher's third-tier sprint is disabled at its only entry
# point NjiwOxnT (the only function that fires W_uuFNS8If). Side effect (not patched, user's call): SpeedUpdate
# still takes the NjiwOxnT(TRUE) branch while VGhoMVNB() is TRUE, skipping its speed-index update while L3 is held.
patch('action/script/c0000.hks',
      b'function NjiwOxnT(pfy4Znys)\r\n',
      b'function NjiwOxnT(pfy4Znys)\r\n'
      b'do return FALSE end -- merge 2026-09-30: Suncatcher third-tier sprint disabled, L3 belongs to NRM\r\n')

# Decision 1.3: no NRM sprint while Suncatcher's stance SpEffect 102032 is active (1116 = GetSpEffectID).
ALLOWED = (b'    local allowed=NRM.surge and input>=0 and NrmOriginalEnv(1000)>0 and NrmOriginalEnv(1116,8001)==FALSE'
           b' and NrmOriginalEnv(234)==FALSE and NrmOriginalEnv(1001)>0 and NrmOriginalEnv(1116,100020)==FALSE'
           b' and math.mod(NrmOriginalEnv(257),20)~=WEIGHT_OVERWEIGHT')
patch('action/script/nrm-extension.hks',
      ALLOWED + b'\n',
      ALLOWED + b' and NrmOriginalEnv(1116,102032)==FALSE -- merge 2026-09-30: no surge during Suncatcher stance\n')
