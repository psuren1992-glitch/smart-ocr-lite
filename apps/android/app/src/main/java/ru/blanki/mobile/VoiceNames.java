package ru.blanki.mobile;

import java.util.*;

final class VoiceNames {
    static String clean(String value) {
        if(value==null)return "";
        return value.replace('\u00a0',' ').replaceAll("[,;]"," ")
            .replaceAll("\\s+"," ").replaceAll("\\s*-\\s*","-").trim()
            .replaceAll("[.!?]+$","").trim();
    }
    static List<String> candidates(List<String> values) {
        Set<String> out=new LinkedHashSet<>();
        if(values!=null)for(String raw:values) {
            String name=clean(raw);
            if(!name.isEmpty()&&name.length()<=200)out.add(name);
            if(out.size()==3)break;
        }
        return new ArrayList<>(out);
    }
    static String russianLanguage(List<String> languages) {
        if(languages!=null)for(String language:languages) {
            if(language==null)continue;
            String normalized=language.replace('_','-');
            if(Locale.forLanguageTag(normalized).getLanguage().equals("ru"))return normalized;
        }
        return "";
    }
}
