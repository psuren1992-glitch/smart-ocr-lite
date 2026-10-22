package ru.blanki.mobile;

import java.util.*;
import java.text.Normalizer;

public final class Profile {
    public static final String[] IDS={"oge_math","ege_base","ege_profile","oge_russian","ege_russian"};
    public static final String[] LABELS={"ОГЭ · Математика","ЕГЭ · Математика, база","ЕГЭ · Математика, профиль","ОГЭ · Русский язык (пилот)","ЕГЭ · Русский язык (пилот)"};
    public static int start(String p){return p.equals("oge_russian")?2:1;}
    public static int end(String p){return switch(p){case "ege_base"->21;case "ege_profile","oge_russian"->12;case "ege_russian"->26;default->19;};}
    public static boolean russian(String p){return p.endsWith("russian");}
    public static boolean ege(String p){return p.startsWith("ege");}
    public static String label(String p){int i=Arrays.asList(IDS).indexOf(p);return i<0?p:LABELS[i];}
    public static int max(String p,int t){return p.equals("ege_russian")&&(t==8||t==22)?2:1;}
    public static String variant(String s){s=s.trim();if(!s.matches("[0-9]{1,2}"))return "";return String.valueOf(Integer.parseInt(s));}
    static String normalize(String p,String s){
        return russian(p)?Normalizer.normalize(s,Normalizer.Form.NFC).toUpperCase(Locale.ROOT).replaceAll("\\s+",""):s.trim().replace(" ","").replace('.',',');
    }
    public static int points(String p,int t,String actual,String key){
        if(actual.isEmpty()||key.isEmpty())return 0;
        actual=normalize(p,actual); int best=0;
        for(String raw:key.split("\\|")){
            String expected=normalize(p,raw);int score=0;
            if(max(p,t)==2){
                if(expected.matches("[0-9]{5}")&&actual.matches("[0-9]{1,5}")){
                    int errors=0;for(int i=0;i<5;i++)if(i>=actual.length()||actual.charAt(i)!=expected.charAt(i))errors++;
                    score=errors==0?2:errors<=2?1:0;
                }
            } else {
                Set<Integer> unordered=p.equals("oge_russian")?Set.of(2,3,5,6,7,10,11):Set.of(2,3,4,9,10,11,12,13,14,15,16,17,18,19,20,21,23,24,26);
                if(russian(p)&&unordered.contains(t)&&actual.matches("[0-9]+")&&expected.matches("[0-9]+")){
                    char[] a=actual.toCharArray(),b=expected.toCharArray();Arrays.sort(a);Arrays.sort(b);score=Arrays.equals(a,b)?1:0;
                }else score=actual.equals(expected)?1:0;
            }
            best=Math.max(best,score);
        }
        return best;
    }
    public static Map<String,Integer> manual(String p){
        Map<String,Integer> m=new LinkedHashMap<>();
        switch(p){
            case "ege_base":break;
            case "ege_profile":int[] max={2,3,2,2,3,4,4};for(int i=0;i<7;i++)m.put(""+(13+i),max[i]);break;
            case "oge_russian":m.put("1",6);m.put("13",7);m.put("Грамотность",13);break;
            case "ege_russian":m.put("27",22);break;
            default:for(int i=20;i<=25;i++)m.put(""+i,2);
        }
        return m;
    }
}
