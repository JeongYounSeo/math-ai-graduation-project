"""프로젝트 루트 conftest.py.

pytest 를 `pytest`(직접 실행)로 돌릴 때도 프로젝트 루트가 sys.path 에 들어가
`import app...` 이 항상 되도록 보장한다. (루트 conftest 가 있으면 pytest 가 그
디렉토리를 rootdir/sys.path 에 추가한다.) 이게 없으면 `python -m pytest` 로만
동작하고 `pytest tests/...` 는 ModuleNotFoundError: No module named 'app' 로 실패한다.

tests/conftest.py 는 네트워크 차단·DB 픽스처 등 테스트 인프라를 담당하고,
이 파일은 경로 보장만 담당한다.
"""

import os
import sys

# 이 파일이 있는 디렉토리(=프로젝트 루트)를 sys.path 맨 앞에 넣는다.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
