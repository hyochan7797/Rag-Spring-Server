package com.example.chatbotproject.batch;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.JobExecution;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class LoanDataRefreshScheduler {

    private final JobLauncher jobLauncher;
    private final Job loanDataRefreshJob;

    @Scheduled(cron = "${loan-refresh.cron:0 0 2 * * *}", zone = "${loan-refresh.zone:Asia/Seoul}")
    public void scheduledRefresh() {
        log.info("[Scheduler] Scheduled FSS refresh started");
        run("scheduled");
    }

    public JobExecution run(String triggeredBy) {
        try {
            JobParameters params = new JobParametersBuilder()
                    .addLong("timestamp", System.currentTimeMillis())
                    .addString("triggeredBy", triggeredBy)
                    .toJobParameters();

            JobExecution execution = jobLauncher.run(loanDataRefreshJob, params);
            log.info("[Scheduler] Batch finished. status={}, triggeredBy={}", execution.getStatus(), triggeredBy);
            return execution;

        } catch (Exception e) {
            log.error("[Scheduler] Batch failed: {}", e.getMessage(), e);
            throw new RuntimeException("Batch execution failed", e);
        }
    }
}
