(function () {
  const apiBase = new URLSearchParams(location.search).get("apiBase") || "/api";
  const endpoint = (path) => apiBase + path;
  const serviceOf = (item) => item.labels?.service || item.subject_key || "unknown";
  const itemId = (item) => `${item.metric_id}:${item.subject_key}:${item.evaluated_at}`;

  function anomaly(item) {
    return {
      id: itemId(item),
      metric: item.metric_id || "unknown_metric",
      service: serviceOf(item),
      status: item.status || "unknown",
      current: item.current_value,
      baseline: item.baseline?.mean,
      change: item.change_rate,
      zScore: item.z_score,
      evaluatedAt: item.evaluated_at,
      raw: item
    };
  }

  window.loadOperationsLiveData = async function (dashboard) {
    const hours = document.querySelector("#periodFilter").value;
    const end = new Date();
    const start = new Date(end.getTime() - Number(hours) * 60 * 60 * 1000);
    const query = `start_at=${encodeURIComponent(start.toISOString())}&end_at=${encodeURIComponent(end.toISOString())}&limit=500`;
    const investigation = dashboard.logInvestigation;
    const investigationStart = investigation?.startAt && new Date(investigation.startAt);
    const investigationEnd = investigation?.endAt && new Date(investigation.endAt);
    const logQuery = investigationStart && investigationEnd
      && !Number.isNaN(investigationStart.getTime()) && !Number.isNaN(investigationEnd.getTime())
      ? `start_at=${encodeURIComponent(investigationStart.toISOString())}&end_at=${encodeURIComponent(investigationEnd.toISOString())}&limit=500`
      : query;
    const [anomalyResponse, incidentResponse, summaryResponse, sourceResponse] = await Promise.all([
      fetch(endpoint(`/internal/anomalies?${query}`)),
      fetch(endpoint(`/internal/incidents?${query}`)),
      fetch(endpoint(`/dashboard/summary?${query}`)),
      fetch(endpoint("/dashboard/sources"))
    ]);
    if (!anomalyResponse.ok || !incidentResponse.ok || !summaryResponse.ok) {
      throw new Error("Operations dashboard data request failed");
    }
    dashboard.anomalies = (await anomalyResponse.json()).map(anomaly);
    dashboard.incidents = await incidentResponse.json();
    dashboard.summary = await summaryResponse.json();
    dashboard.sources = sourceResponse.ok ? await sourceResponse.json() : {};
    const snapshots = await Promise.all(dashboard.incidents.slice(0, 20).map(async (incident) => {
      const response = await fetch(endpoint(`/internal/incidents/${encodeURIComponent(incident.incident_id)}/evidence/latest`));
      if (!response.ok) return [incident.incident_id, null];
      const snapshot = await response.json();
      return [incident.incident_id, snapshot.snapshot_id ? snapshot : null];
    }));
    dashboard.snapshots = Object.fromEntries(snapshots);
    dashboard.source = "live";

    dashboard.serviceRequestRate = [];
    dashboard.topCpuPods = [];
    dashboard.topMemoryPods = [];
    dashboard.nodeCpu = [];
    dashboard.nodeMemory = [];
    dashboard.nodeDisk = [];
    dashboard.nodeInfo = [];
    dashboard.nodeCpuTimeseries = [];
    dashboard.nodeMemoryTimeseries = [];
    dashboard.nodeDiskTimeseries = [];
    dashboard.nodeNetworkTimeseries = [];
    dashboard.kafkaLag = [];
    dashboard.pipelineRecords = [];
    dashboard.pipelineSinkWrites = [];
    dashboard.pipelineProcessing = [];
    dashboard.pipelineMatchQuality = [];
    dashboard.podRestarts = [];
    dashboard.networkIO = [];
    dashboard.memoryTimeseries = [];
    dashboard.cpuTimeseries = [];
    dashboard.serviceP95Timeseries = [];
    dashboard.serviceP50Timeseries = [];
    dashboard.serviceP99Timeseries = [];
    dashboard.service4xxRateTimeseries = [];
    dashboard.serviceErrorRateTimeseries = [];
    dashboard.podCpuTimeseries = [];
    dashboard.podMemoryTimeseries = [];
    dashboard.containerCpuTimeseries = [];
    dashboard.containerMemoryTimeseries = [];
    dashboard.errorRateTimeseries = [];
    dashboard.rpsTimeseries = [];
    dashboard.p95Timeseries = [];
    dashboard.responseCodeBreakdown = [];
    dashboard.overview = { rps: null, errorRatePercent: null, p95Ms: null };
    if (dashboard.sources.prometheus?.enabled) {
      const instant = async (promql) => {
        const response = await fetch(endpoint(`/prometheus/query?promql=${encodeURIComponent(promql)}`));
        return response.ok ? response.json() : [];
      };
      try {
        const promql = 'sum by(service) (rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))';
        const step = Math.max(15, Math.round((end.getTime() - start.getTime()) / 1000 / 120));
        const promResponse = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(promql)}`)
        );
        if (promResponse.ok) dashboard.serviceRequestRate = await promResponse.json();
        dashboard.topCpuPods = await instant(
          'sum by(namespace, pod) (rate(container_cpu_usage_seconds_total{namespace!="", container!="", container!="POD", image!=""}[5m]))'
        );
        dashboard.topMemoryPods = await instant(
          'sum by(namespace, pod) (container_memory_working_set_bytes{namespace!="", container!="", container!="POD", image!=""})'
        );
        dashboard.nodeCpu = await instant(
          '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
        );
        dashboard.nodeMemory = await instant(
          '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'
        );
        dashboard.nodeDisk = await instant(
          '100 * (1 - (node_filesystem_avail_bytes{mountpoint="/", fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/", fstype!~"tmpfs|overlay"}))'
        );
        dashboard.nodeInfo = await instant("node_uname_info");
        const nodeCpuRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)')}`));
        dashboard.nodeCpuTimeseries = nodeCpuRange.ok ? await nodeCpuRange.json() : [];
        const nodeMemoryRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))')}`));
        dashboard.nodeMemoryTimeseries = nodeMemoryRange.ok ? await nodeMemoryRange.json() : [];
        const nodeDiskRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('100 * (1 - (node_filesystem_avail_bytes{mountpoint="/", fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/", fstype!~"tmpfs|overlay"}))')}`));
        dashboard.nodeDiskTimeseries = nodeDiskRange.ok ? await nodeDiskRange.json() : [];
        const nodeNetworkRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|cali.*|cilium.*|lxc.*|docker.*|br-.*"}[5m]))')}`));
        dashboard.nodeNetworkTimeseries = nodeNetworkRange.ok ? await nodeNetworkRange.json() : [];
        dashboard.kafkaLag = await instant("topk(5, sum by(consumergroup, topic) (kafka_consumergroup_lag))");
        const pipelineRecordsRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('sum by(component, result) (rate(fb_pipeline_records_total[5m]))')}`));
        dashboard.pipelineRecords = pipelineRecordsRange.ok ? await pipelineRecordsRange.json() : [];
        const sinkRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('sum by(component, sink, result) (rate(fb_pipeline_sink_writes_total[5m]))')}`));
        dashboard.pipelineSinkWrites = sinkRange.ok ? await sinkRange.json() : [];
        const processingRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent('histogram_quantile(0.95, sum by(component, le) (rate(fb_pipeline_processing_duration_seconds_bucket[5m]))) * 1000')}`));
        dashboard.pipelineProcessing = processingRange.ok ? await processingRange.json() : [];
        dashboard.pipelineMatchQuality = await instant('100 * sum by(component) (rate(fb_pipeline_item_matches_total{result="matched"}[5m])) / clamp_min(sum by(component) (rate(fb_pipeline_item_matches_total[5m])), 0.001)');
        dashboard.podRestarts = await instant(
          'sum by(namespace, pod) (increase(kube_pod_container_status_restarts_total{namespace!=""}[1h]))'
        );
        dashboard.networkIO = await instant(
          'sum by(namespace, pod) (rate(container_network_transmit_bytes_total{namespace!=""}[5m]))'
        );
        const memoryPromql = 'sum(container_memory_working_set_bytes{namespace="app", container!="", container!="POD", container!="istio-proxy", image!=""})';
        const memoryRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(memoryPromql)}`)
        );
        dashboard.memoryTimeseries = memoryRange.ok ? await memoryRange.json() : [];
        const cpuPromql = 'sum(rate(container_cpu_usage_seconds_total{namespace="app", container!="", container!="POD", container!="istio-proxy", image!=""}[5m]))';
        const cpuRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(cpuPromql)}`)
        );
        dashboard.cpuTimeseries = cpuRange.ok ? await cpuRange.json() : [];
        const serviceP95Promql = 'histogram_quantile(0.95, sum by(service, le) (rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m]))) * 1000';
        const serviceP95Range = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(serviceP95Promql)}`)
        );
        dashboard.serviceP95Timeseries = serviceP95Range.ok ? await serviceP95Range.json() : [];
        const serviceP50Promql = 'histogram_quantile(0.50, sum by(service, le) (rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m]))) * 1000';
        const serviceP50Range = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(serviceP50Promql)}`));
        dashboard.serviceP50Timeseries = serviceP50Range.ok ? await serviceP50Range.json() : [];
        const serviceP99Promql = 'histogram_quantile(0.99, sum by(service, le) (rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m]))) * 1000';
        const serviceP99Range = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(serviceP99Promql)}`));
        dashboard.serviceP99Timeseries = serviceP99Range.ok ? await serviceP99Range.json() : [];
        // 5xx가 한 건도 없으면 Prometheus는 분자를 빈 vector로 반환한다. 요청이 있는 서비스의
        // 0%도 실제 관측값으로 표시하도록, 전체 요청 label 집합에서 0 series를 만든 뒤 합친다.
        const serviceErrorPromql = '100 * (sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app", response_code=~"5.."}[5m])) or on(destination_service_name) (0 * sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app"}[5m])))) / clamp_min(sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app"}[5m])), 0.001)';
        const serviceErrorRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(serviceErrorPromql)}`)
        );
        dashboard.serviceErrorRateTimeseries = serviceErrorRange.ok ? await serviceErrorRange.json() : [];
        const service4xxPromql = '100 * (sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app", response_code=~"4.."}[5m])) or on(destination_service_name) (0 * sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app"}[5m])))) / clamp_min(sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app"}[5m])), 0.001)';
        const service4xxRange = await fetch(endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(service4xxPromql)}`));
        dashboard.service4xxRateTimeseries = service4xxRange.ok ? await service4xxRange.json() : [];
        const podCpuPromql = 'sum by(namespace, pod) (rate(container_cpu_usage_seconds_total{namespace!="", container!="", container!="POD", image!=""}[5m]))';
        const podCpuRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(podCpuPromql)}`)
        );
        dashboard.podCpuTimeseries = podCpuRange.ok ? await podCpuRange.json() : [];
        const podMemoryPromql = 'sum by(namespace, pod) (container_memory_working_set_bytes{namespace!="", container!="", container!="POD", image!=""})';
        const podMemoryRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(podMemoryPromql)}`)
        );
        dashboard.podMemoryTimeseries = podMemoryRange.ok ? await podMemoryRange.json() : [];
        const containerCpuPromql = 'sum by(namespace, pod, container) (rate(container_cpu_usage_seconds_total{namespace!="", container!="", container!="POD", image!=""}[5m]))';
        const containerCpuRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(containerCpuPromql)}`)
        );
        dashboard.containerCpuTimeseries = containerCpuRange.ok ? await containerCpuRange.json() : [];
        const containerMemoryPromql = 'sum by(namespace, pod, container) (container_memory_working_set_bytes{namespace!="", container!="", container!="POD", image!=""})';
        const containerMemoryRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(containerMemoryPromql)}`)
        );
        dashboard.containerMemoryTimeseries = containerMemoryRange.ok ? await containerMemoryRange.json() : [];
        // Rate·Duration은 Anomaly Analyzer가 쓰는 정본 앱 메트릭을 그대로 재사용(Istio 프록시 측 값과 불일치 방지).
        dashboard.serviceRate = await instant('sum by(service) (rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))');
        dashboard.serviceDuration = await instant('histogram_quantile(0.95, sum by(service, le) (rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m])))');
        // Error(5xx)만 앱 메트릭에 없는 유일한 조각이라 Istio 메시 텔레메트리로 보완.
        dashboard.serviceErrorRate = await instant('sum by(destination_service_name) (rate(istio_requests_total{destination_service_namespace="app", response_code=~"5.."}[5m]))');
        // Overview용 전체 집계(서비스별 아님) — 전체 RPS/5xx율/p95.
        const totalRps = await instant('sum(rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))');
        const totalRequests = await instant('sum(rate(istio_requests_total{destination_service_namespace="app"}[5m]))');
        const totalErrors = await instant('sum(rate(istio_requests_total{destination_service_namespace="app", response_code=~"5.."}[5m]))');
        const overallP95 = await instant('histogram_quantile(0.95, sum(rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m])) by (le))');
        dashboard.overview = {
          rps: totalRps[0] ? Number(totalRps[0].value[1]) : null,
          errorRatePercent: totalRequests[0] && Number(totalRequests[0].value[1]) > 0
            ? (Number(totalErrors[0]?.value[1] || 0) / Number(totalRequests[0].value[1])) * 100
            : null,
          // Prometheus는 histogram bucket이 없을 때 빈 값 대신 "NaN"을 반환할 수 있다.
          // 화면에서 "- ms" 같은 가짜 수치가 되지 않도록 명시적으로 미수집(null) 처리한다.
          p95Ms: overallP95[0] && Number.isFinite(Number(overallP95[0].value[1]))
            ? Number(overallP95[0].value[1]) * 1000
            : null,
        };
        // Atatus의 "HTTP Failure Rate" 추이 + "HTTP Failure Codes" 분포 참고.
        // sum(rate(...))는 매칭되는 시계열이 하나도 없으면(예: 5xx가 한 번도 없음) "0"이 아니라
        // 결과 자체가 없는 빈 벡터를 돌려준다 — `or vector(0)`로 항상 값이 존재하게 강제한다.
        const errorRatePromql = '100 * (sum(rate(istio_requests_total{destination_service_namespace="app", response_code=~"5.."}[5m])) or vector(0)) / clamp_min((sum(rate(istio_requests_total{destination_service_namespace="app"}[5m])) or vector(0)), 0.001)';
        const errorRateRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(errorRatePromql)}`)
        );
        dashboard.errorRateTimeseries = errorRateRange.ok ? await errorRateRange.json() : [];
        const totalRpsPromql = 'sum(rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))';
        const totalRpsRange = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(totalRpsPromql)}`)
        );
        dashboard.rpsTimeseries = totalRpsRange.ok ? await totalRpsRange.json() : [];
        const p95Promql = 'histogram_quantile(0.95, sum(rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m])) by (le)) * 1000';
        const p95Range = await fetch(
          endpoint(`/prometheus/query_range?${query}&step=${step}&promql=${encodeURIComponent(p95Promql)}`)
        );
        dashboard.p95Timeseries = p95Range.ok ? await p95Range.json() : [];
        dashboard.responseCodeBreakdown = await instant(
          'sum by(response_code) (rate(istio_requests_total{destination_service_namespace="app"}[5m]))'
        );
      } catch (error) {
        console.warn("Prometheus query unavailable", error);
      }
    } else {
      dashboard.serviceRate = [];
      dashboard.serviceErrorRate = [];
      dashboard.serviceDuration = [];
      dashboard.nodeCpu = [];
      dashboard.nodeMemory = [];
      dashboard.nodeDisk = [];
      dashboard.nodeInfo = [];
      dashboard.nodeCpuTimeseries = [];
      dashboard.nodeMemoryTimeseries = [];
      dashboard.nodeDiskTimeseries = [];
      dashboard.nodeNetworkTimeseries = [];
      dashboard.cpuTimeseries = [];
      dashboard.serviceP95Timeseries = [];
      dashboard.serviceP50Timeseries = [];
      dashboard.serviceP99Timeseries = [];
      dashboard.service4xxRateTimeseries = [];
      dashboard.serviceErrorRateTimeseries = [];
      dashboard.podCpuTimeseries = [];
      dashboard.podMemoryTimeseries = [];
      dashboard.containerCpuTimeseries = [];
      dashboard.containerMemoryTimeseries = [];
      dashboard.errorRateTimeseries = [];
      dashboard.rpsTimeseries = [];
      dashboard.p95Timeseries = [];
      dashboard.responseCodeBreakdown = [];
      dashboard.overview = { rps: null, errorRatePercent: null, p95Ms: null };
    }

    dashboard.platformHealth = [];
    dashboard.deployEvents = [];
    dashboard.kubernetesWorkloadEvents = [];
    if (dashboard.sources.kubernetes?.enabled) {
      try {
        const healthResponse = await fetch(endpoint("/kubernetes/pod-health?namespace=app&namespace=data&namespace=pipeline"));
        if (healthResponse.ok) dashboard.platformHealth = await healthResponse.json();
        const workloadResponse = await fetch(endpoint("/kubernetes/workload-events?namespace=app&namespace=data&namespace=pipeline"));
        if (workloadResponse.ok) dashboard.kubernetesWorkloadEvents = await workloadResponse.json();
        const deployResponse = await fetch(endpoint("/kubernetes/deploy-events?namespace=app&namespace=data&namespace=pipeline"));
        if (deployResponse.ok) dashboard.deployEvents = await deployResponse.json();
      } catch (error) {
        console.warn("Kubernetes query unavailable", error);
      }
    }

    dashboard.errorLogs = [];
    dashboard.issueLogs = [];
    dashboard.traceLogs = [];
    dashboard.logFacets = [];
    if (dashboard.sources.loki?.enabled) {
      try {
        // 전체 원문과 별도로, Loki가 ERROR/WARN 패턴을 서버 쪽에서 먼저 거른 결과를
        // 조회한다. 전체 로그 500행을 받은 뒤 브라우저에서 필터링하면 INFO 폭주 시
        // 실제 오류가 limit 밖으로 밀려나는 문제가 생긴다.
        // namespace/Pod/container는 원문 결과를 받은 뒤 브라우저에서 자르는 용도가
        // 아니라 Loki stream label을 직접 제한한다. 그래야 Redis Pod처럼 INFO가 많은
        // 대상도 최근 전역 500행 밖으로 밀려나지 않는다.
        const filterValue = (name) => document.querySelector(`[data-log-select="${name}"]`)?.value || "all";
        const selectedNamespace = filterValue("namespace");
        const selectedPod = filterValue("pod");
        const selectedContainer = filterValue("container");
        const selectorParts = [selectedNamespace === "all" ? 'namespace=~"app|data|pipeline"' : `namespace=${JSON.stringify(selectedNamespace)}`];
        if (selectedPod !== "all") selectorParts.push(`pod=${JSON.stringify(selectedPod)}`);
        if (selectedContainer !== "all") selectorParts.push(`container=${JSON.stringify(selectedContainer)}`);
        const logSelector = `{${selectorParts.join(",")}}`;
        // 키워드는 서비스명이 아니라 실제 원문 메시지 포함 검색이다.
        const keyword = document.querySelector("[data-log-filter]")?.value.trim() || "";
        const messageFilter = keyword ? ` |= ${JSON.stringify(keyword)}` : "";
        const allLogql = `${logSelector}${messageFilter}`;
        const issueLogql = `${logSelector} |~ "(?i)(error|warn|fatal|panic|exception|traceback)"${messageFilter}`;
        const traceId = dashboard.logInvestigation?.traceId || "";
        // Trace ID는 Loki stream label이 아닐 수도 있으므로, 원문에 포함된 ID를
        // 우선 검색한다. 결과가 없으면 app.js가 서비스·시간 범위 결과로 폴백한다.
        const traceLogql = traceId ? `${logSelector} |= ${JSON.stringify(traceId)}` : "";
        if (dashboard.logInvestigation) dashboard.logInvestigation.query = traceLogql;
        const requests = [
          fetch(endpoint(`/loki/query_range?${logQuery}&logql=${encodeURIComponent(allLogql)}`)),
          fetch(endpoint(`/loki/query_range?${logQuery}&logql=${encodeURIComponent(issueLogql)}`)),
        ];
        if (traceLogql) requests.push(fetch(endpoint(`/loki/query_range?${logQuery}&logql=${encodeURIComponent(traceLogql)}`)));
        const [allResponse, issueResponse, traceResponse] = await Promise.all(requests);
        if (allResponse.ok) dashboard.errorLogs = await allResponse.json();
        if (issueResponse.ok) dashboard.issueLogs = await issueResponse.json();
        if (traceResponse?.ok) dashboard.traceLogs = await traceResponse.json();
        const facetsResponse = await fetch(endpoint(`/loki/facets?${logQuery}`));
        if (facetsResponse.ok) dashboard.logFacets = await facetsResponse.json();
      } catch (error) {
        console.warn("Loki query unavailable", error);
      }
    }

    dashboard.recentTraces = [];
    dashboard.errorTraces = [];
    if (dashboard.sources.tempo?.enabled) {
      try {
        // 게이트웨이(mp-gw-*)·operations 자체의 Prometheus 조회 등 인프라 노이즈를 빼고
        // 실제 앱 서비스 트래픽만 본다.
        const appServices = "account|chat|frontend|mealplan|notify|ocr|pantry|price|recipe|recipebook";
        const traceql = encodeURIComponent(`{resource.service.name=~"${appServices}"}`);
        const response = await fetch(endpoint(`/tempo/search?${query}&q=${traceql}`));
        if (response.ok) dashboard.recentTraces = await response.json();
        const errorTraceql = encodeURIComponent(`{resource.service.name=~"${appServices}" && status=error}`);
        const errorResponse = await fetch(endpoint(`/tempo/search?${query}&q=${errorTraceql}`));
        if (errorResponse.ok) dashboard.errorTraces = await errorResponse.json();
      } catch (error) {
        console.warn("Tempo query unavailable", error);
      }
    }
    return dashboard;
  };

  // Trace 목록에서 사용자가 명시적으로 선택한 한 건만 상세 조회한다.
  // Tempo/클러스터에 쓰지 않는 로컬 read-only 요청이다.
  window.loadOperationsTraceDetail = async function (dashboard, traceId) {
    dashboard.selectedTrace = null;
    dashboard.selectedTraceError = "";
    if (!dashboard.sources?.tempo?.enabled || !traceId) return dashboard;
    const response = await fetch(endpoint(`/tempo/trace?trace_id=${encodeURIComponent(traceId)}`));
    if (!response.ok) {
      const message = (await response.text()).trim().replace(/\s+/g, " ");
      dashboard.selectedTraceError = `${response.status}${message ? ` · ${message.slice(0, 180)}` : ""}`;
      throw new Error(`Tempo trace detail request failed (${response.status})`);
    }
    dashboard.selectedTrace = await response.json();
    return dashboard;
  };
})();
