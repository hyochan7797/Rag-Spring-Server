package com.example.chatbotproject.repository;

import com.example.chatbotproject.entity.ChatConversationSummary;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ChatConversationSummaryRepository extends JpaRepository<ChatConversationSummary, Long> {
    Optional<ChatConversationSummary> findByUserId(Long userId);
}
