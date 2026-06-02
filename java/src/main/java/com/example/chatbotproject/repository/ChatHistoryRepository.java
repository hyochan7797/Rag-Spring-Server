package com.example.chatbotproject.repository;

import com.example.chatbotproject.entity.ChatHistory;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface ChatHistoryRepository extends JpaRepository<ChatHistory, Long> {
    @Query("""
            select h
            from ChatHistory h
            where h.userId = :userId
              and (h.ragEligible = true or h.ragEligible is null)
            order by h.timestamp desc, h.id desc
            """)
    List<ChatHistory> findRecentRagHistory(@Param("userId") Long userId, Pageable pageable);
}
