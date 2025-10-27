package com.example.chatbotproject.security;

import com.example.chatbotproject.entity.User;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Component
@RequiredArgsConstructor
public class LoginSuccessHandler implements AuthenticationSuccessHandler {

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request,
                                        HttpServletResponse response,
                                        Authentication authentication) throws IOException {

        // 인증된 사용자 정보 가져오기
        User user = (User) authentication.getPrincipal();

        // 세션에 userId 저장
        HttpSession session = request.getSession();
        session.setAttribute("userId", user.getId());

        // 로그인 성공 후 이동할 페이지
        response.sendRedirect("/chat");
    }
}
