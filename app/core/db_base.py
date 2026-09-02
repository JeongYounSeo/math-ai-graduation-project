from sqlalchemy.orm import declarative_base

# 별도 모듈로 분리한 이유: app/core/database.py는 테스트에서 DB를 바꾸기 위해
# importlib.reload()되는데, Base를 database.py 안에서 정의하면 reload될 때마다
# 새 Base(및 새 MetaData)가 생겨서 이미 import된 모델과 이제 막 import되는 모델이
# 서로 다른 metadata에 등록된다. 그 결과 모델 간 ForeignKey가 상대 테이블을 찾지
# 못하는 오류가 발생한다. 이 모듈은 reload 대상이 아니므로 Base 정체성이 유지된다.
Base = declarative_base()
