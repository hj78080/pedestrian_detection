import cv2
import time
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import redis

CONFIDENCE_THRESHOLD = 0.65
GREEN = (0, 255, 0)
WHITE = (255, 255, 255)

model = YOLO('yolov8n.pt')
model = YOLO('./runs/detect/train/weights/best.pt')
tracker = DeepSort(max_age=50)

url = "http://cctvsec.ktict.co.kr/9999/7Hcw88TE2LcuSJfVUaH3av6VVB7e+jnwH4CIG87AqRctrfrPl7Q7R83SZuNsqt9V" # cctv url
cap = cv2.VideoCapture(url)

x1,y1 = 120,300     # cctv 영상 중 원하는 구역만 자르기 frame = frame[y1:y2, x1:x2]
x2,y2 = 360,420    # 필요한 부분만 잘라 확대하여 리소스 낭비 줄이고 검출에 용이하게 함

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

track_active = {}

# Redis 연결 설정
redis_host = 'localhost'  # Redis 서버 주소
redis_port = 6379         # Redis 포트
redis_db = 0              # 사용할 Redis 데이터베이스 번호
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db)

while True:
    ret, frame = cap.read()
    if not ret:
        print('Cam Error')
        break
    
    frame = frame[y1:y2, x1:x2]
    frame = cv2.resize(frame, ((x2-x1)*2, (y2-y1)*2), interpolation=cv2.INTER_LINEAR)   #영상 확대

    detection = model.predict(source=[frame], save=False)[0]
    results = []

    #---------------------------------------------------------
    # 영상을 탐색하여 사람 발견 시 정보를 results에 추가
    #---------------------------------------------------------
    for data in detection.boxes.data.tolist():
        confidence = float(data[4])
        if confidence < CONFIDENCE_THRESHOLD:
            continue

        xmin, ymin, xmax, ymax = int(data[0]), int(data[1]), int(data[2]), int(data[3])
        class_id = int(data[5])

        if class_id == 0:
            results.append([[xmin, ymin, xmax - xmin, ymax - ymin], confidence, class_id])

    tracks = tracker.update_tracks(results, frame=frame)

    #---------------------------------------------------------
    # detection 으로 구한 대상에게 traker 부여하며 구간 속력 계산
    #---------------------------------------------------------
    for track in tracks:
        if not track.is_confirmed():
            continue

        track_id = track.track_id
        ltrb = track.to_ltrb()

        #발견한 대상에 사각형과 id 표시
        xmin, ymin, xmax, ymax = int(ltrb[0]), int(ltrb[1]), int(ltrb[2]), int(ltrb[3])
        cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), GREEN, 2)
        cv2.putText(frame, f"{track_id}", (xmin, ymin-20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREEN, 2)

        #현재 위치 설정. 횡단보도를 x 방향으로 이동하기 때문에 x 좌표만 판단
        current_location = (xmin+xmax)/2

        #처음 발견한 대상일 경우 [시작시간, 시작위치] 저장
        if track_id not in track_active:
            track_active[track_id] = [time.time(), current_location]
        
        #기존에 있던 대상일 경우, (지금시간-시작시간)을 구함
        else :
            time_interval = time.time() - track_active[track_id][0]
            cv2.putText(frame, f"%.2f"%(time_interval), (xmin+20, ymin-20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 2)

            #임계값 5초, 5pix/s 가 넘어갈 경우, 적합한 대상이라고 판단하여 구간 속력을 구해 Redis에 저장
            if time_interval >= 5 :
                start_location = track_active[track_id][1]
                del track_active[track_id]

                distance = abs(current_location-start_location)
                average_velocity = round(distance / time_interval, 2)

                if average_velocity > 5 : redis_client.set(track_id, average_velocity)

    cv2.imshow('frame', frame)

    if cv2.waitKey(1) == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()