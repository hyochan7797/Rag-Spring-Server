package com.example.chatbotproject.batch;

import org.springframework.batch.core.Job;
import org.springframework.batch.core.Step;
import org.springframework.batch.core.job.builder.JobBuilder;
import org.springframework.batch.core.repository.JobRepository;
import org.springframework.batch.core.step.builder.StepBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.PlatformTransactionManager;

@Configuration
@EnableScheduling
public class BatchConfig {

    @Bean
    public Job loanDataRefreshJob(JobRepository jobRepository, Step fssRefreshStep) {
        return new JobBuilder("loanDataRefreshJob", jobRepository)
                .start(fssRefreshStep)
                .build();
    }

    @Bean
    public Step fssRefreshStep(JobRepository jobRepository,
                               PlatformTransactionManager txManager,
                               FssRefreshTasklet tasklet) {
        return new StepBuilder("fssRefreshStep", jobRepository)
                .tasklet(tasklet, txManager)
                .build();
    }
}
