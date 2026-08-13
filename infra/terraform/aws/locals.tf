# 스트림 = 구 Kafka 토픽 3종과 1:1. 큐를 스트림별로 가르는 이유:
#   ① 컨슈머 Deployment 가 이미 3개고 각자 다른 테이블을 쓴다. 큐가 하나면 남의 메시지를 받은
#      컨슈머가 되돌려놓느라 가시성 타임아웃을 낭비하고, 레시피가 밀리면 소매까지 막힌다.
#   ② SQS 무료한도(100만 요청/월)는 **계정 단위**라 큐를 늘려도 비용이 안 는다.
#      KEDA 폴링만 큐 수에 비례한다 — 30초 폴링 × 3큐 = 월 약 26만 요청(한도의 26%).
#
# max_consumers = 일일 객체 수. 평시 동시성은 1이지만(시각이 흩어져 있다) 리파이너가 하루 멈춰
#   밀렸을 때 그날치를 병렬로 빼낼 수 있는 상한이다. 적재 SQL 이 전부 멱등이라 병렬이 안전하다.
locals {
  streams = {
    # 03:30 kurly · 04:10 oasis-dawn · 13:10 oasis-noon
    retail = {
      objects_per_day = 3
      max_consumers   = 3
    }
    # 15:05 timeSale · 17:05 closeSale
    deal = {
      objects_per_day = 2
      max_consumers   = 2
    }
    # 일·수 05:00 (주 2회)
    recipe = {
      objects_per_day = 1
      max_consumers   = 2
    }
  }

  # 🔴 S3 이벤트 필터는 incoming/ 만 건다. failed/ 까지 걸면 컨슈머가 격리 레코드를 쓸 때마다
  #    새 메시지가 나서 **무한 루프**가 된다.
  incoming_prefix = "incoming/"
  failed_prefix   = "failed/"
}
