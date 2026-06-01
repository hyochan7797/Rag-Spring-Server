package com.example.chatbotproject.batch;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.JobExecution;
import org.springframework.batch.core.JobInstance;
import org.springframework.batch.core.explore.JobExplorer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@RestController
@RequestMapping("/admin/batch")
@RequiredArgsConstructor
public class BatchJobController {

    private final LoanDataRefreshScheduler scheduler;
    private final JobExplorer jobExplorer;

    @Value("${ADMIN_API_KEY:}")
    private String adminApiKey;

    @PostMapping("/refresh")
    public ResponseEntity<Map<String, Object>> triggerRefresh(
            @RequestHeader(value = "X-Admin-Key", required = false) String requestKey) {

        if (adminApiKey.isBlank() || !adminApiKey.equals(requestKey)) {
            return ResponseEntity.status(403).body(Map.of("error", "forbidden"));
        }

        log.info("[BatchController] Manual refresh triggered");
        JobExecution execution = scheduler.run("manual");

        return ResponseEntity.ok(Map.of(
                "status", execution.getStatus().name(),
                "jobId", execution.getJobId(),
                "startTime", String.valueOf(execution.getStartTime())
        ));
    }

    @GetMapping("/status")
    public ResponseEntity<Map<String, Object>> getStatus(
            @RequestHeader(value = "X-Admin-Key", required = false) String requestKey) {

        if (adminApiKey.isBlank() || !adminApiKey.equals(requestKey)) {
            return ResponseEntity.status(403).body(Map.of("error", "forbidden"));
        }

        List<JobInstance> instances = jobExplorer.getJobInstances("loanDataRefreshJob", 0, 1);
        if (instances.isEmpty()) {
            return ResponseEntity.ok(Map.of("status", "NO_EXECUTION"));
        }

        Optional<JobExecution> lastExecution = jobExplorer.getJobExecutions(instances.get(0)).stream()
                .max(Comparator.comparing(JobExecution::getCreateTime));

        if (lastExecution.isEmpty()) {
            return ResponseEntity.ok(Map.of("status", "NO_EXECUTION"));
        }

        JobExecution execution = lastExecution.get();
        return ResponseEntity.ok(Map.of(
                "status", execution.getStatus().name(),
                "jobId", execution.getJobId(),
                "startTime", String.valueOf(execution.getStartTime()),
                "endTime", String.valueOf(execution.getEndTime()),
                "exitCode", execution.getExitStatus().getExitCode()
        ));
    }
}
