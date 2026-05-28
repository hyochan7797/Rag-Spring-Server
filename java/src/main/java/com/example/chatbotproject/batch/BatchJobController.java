package com.example.chatbotproject.batch;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.BatchStatus;
import org.springframework.batch.core.JobExecution;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/admin/batch")
@RequiredArgsConstructor
public class BatchJobController {

    private final LoanDataRefreshScheduler scheduler;

    @Value("${ADMIN_API_KEY:}")
    private String adminApiKey;

    /**
     * 수동으로 FSS 데이터 갱신 배치를 트리거합니다.
     * Header: X-Admin-Key: {ADMIN_API_KEY}
     */
    @PostMapping("/refresh")
    public ResponseEntity<Map<String, Object>> triggerRefresh(
            @RequestHeader(value = "X-Admin-Key", required = false) String requestKey) {

        if (adminApiKey.isBlank() || !adminApiKey.equals(requestKey)) {
            return ResponseEntity.status(403).body(Map.of("error", "인증 실패"));
        }

        log.info("[BatchController] 수동 갱신 트리거");
        JobExecution execution = scheduler.run("manual");

        return ResponseEntity.ok(Map.of(
                "status", execution.getStatus().name(),
                "jobId", execution.getJobId(),
                "startTime", String.valueOf(execution.getStartTime())
        ));
    }

    /**
     * 마지막 배치 실행 결과 조회
     */
    @GetMapping("/status")
    public ResponseEntity<Map<String, Object>> getStatus(
            @RequestHeader(value = "X-Admin-Key", required = false) String requestKey) {

        if (adminApiKey.isBlank() || !adminApiKey.equals(requestKey)) {
            return ResponseEntity.status(403).body(Map.of("error", "인증 실패"));
        }

        // 실제 운영에서는 JobExplorer로 마지막 실행 이력 조회
        return ResponseEntity.ok(Map.of("message", "Spring Batch 정상 동작 중"));
    }
}
