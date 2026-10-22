package ru.blanki.mobile;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

public class VoiceNamesTest {
    @Test public void russianSpellingNotGuessed(){assertEquals("Семёнов Семён Семёнович",VoiceNames.clean(" Семёнов, Семён   Семёнович. "));}
    @Test public void hyphensPreserved(){assertEquals("Анна-Мария",VoiceNames.clean("Анна - Мария"));}
    @Test public void suggestionsDeduplicatedAndLimited(){assertEquals(List.of("Один","Два","Три"),VoiceNames.candidates(List.of("Один.","Один","Два","Три","Четыре")));}
    @Test public void emptyAndLongNamesIgnored(){assertTrue(VoiceNames.candidates(Arrays.asList(null,"  ","а".repeat(201))).isEmpty());}
    @Test public void russianInstalledPackRequired(){assertEquals("",VoiceNames.russianLanguage(List.of("en-US","de-DE")));assertEquals("ru-RU",VoiceNames.russianLanguage(List.of("en-US","ru_RU")));}
    @Test public void bareRussianLanguageAccepted(){assertEquals("ru",VoiceNames.russianLanguage(List.of("ru")));}
}
