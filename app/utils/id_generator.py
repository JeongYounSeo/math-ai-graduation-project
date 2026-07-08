import uuid
import time

def generate_id() -> str:
    """고유 ID 생성"""
    return str(uuid.uuid4())

def generate_timestamp_id() -> str:
    """타임스탬프 기반 ID 생성"""
    return f"{int(time.time())}_{uuid.uuid4().hex[:8]}"