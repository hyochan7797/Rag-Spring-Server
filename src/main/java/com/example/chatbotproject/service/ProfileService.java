package com.example.chatbotproject.service;

import com.example.chatbotproject.entity.Profile;
import com.example.chatbotproject.repository.ProfileRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@RequiredArgsConstructor
public class ProfileService {
    private final ProfileRepository ProfileRepository;

    public List<Profile> getAllProfiles() {
        return ProfileRepository.findAll();
    }

    public Profile createProfile(Profile profile) {
        return ProfileRepository.save(profile);
    }
}
