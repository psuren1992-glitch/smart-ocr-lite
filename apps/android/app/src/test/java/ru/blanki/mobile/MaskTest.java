package ru.blanki.mobile;
import org.junit.Test;
import org.json.*;
import java.util.*;
import static org.junit.Assert.*;
public class MaskTest {
 @Test public void csvDecimalAndLeadingZero()throws Exception{JSONObject keys=MaskReader.parse(MaskReader.csv("\uFEFF№ задания;Вариант 01;Вариант 2\r\n1;-0,68;0968\r\n2;32;3,2\r\n"),"oge_math");assertEquals("-0,68",keys.getJSONObject("1").getString("1"));assertEquals("0968",keys.getJSONObject("2").getString("1"));}
 @Test public void commaQuoted()throws Exception{JSONObject keys=MaskReader.parse(MaskReader.csv("№ задания,Вариант 1\n1,\"3,2\"\n"),"ege_base");assertEquals("3,2",keys.getJSONObject("1").getString("1"));}
 @Test public void extraTaskRejected()throws Exception{try{MaskReader.parse(MaskReader.csv("№;1\n13;42"),"ege_profile");fail();}catch(java.io.IOException expected){assertTrue(expected.getMessage().contains("13"));}}
 @Test public void duplicateVariantRejected()throws Exception{try{MaskReader.parse(MaskReader.csv("№;1;01\n1;4;4"),"oge_math");fail();}catch(java.io.IOException expected){}}
 @Test public void duplicateTaskRejected()throws Exception{try{MaskReader.parse(MaskReader.csv("№;1\n1;4\n1;5"),"oge_math");fail();}catch(java.io.IOException expected){}}
 @Test public void partialRussianKeyRejected()throws Exception{try{MaskReader.parse(MaskReader.csv("№;1\n8;123"),"ege_russian");fail();}catch(java.io.IOException expected){}}
 @Test public void unfinishedQuoteRejected()throws Exception{try{MaskReader.csv("a;b\n1;\"oops");fail();}catch(java.io.IOException expected){}}
 @Test public void answerSheetOnly()throws Exception{assertTrue(Exports.answer(new JSONObject().put("kind","answers")));assertFalse(Exports.answer(new JSONObject().put("kind","registration")));assertFalse(Exports.answer(new JSONObject().put("kind","manual")));}
 @Test public void missingKeyIsNotZero()throws Exception{JSONObject w=new JSONObject().put("profile","oge_math").put("keys",new JSONObject());JSONObject p=new JSONObject().put("reviewed",true).put("variant","1").put("answers",new JSONObject());assertEquals("Нет ключа",Exports.score(w,p));p.put("reviewed",false);assertEquals("Не сверено",Exports.score(w,p));}
 @Test public void egeRequiresRegistration()throws Exception{JSONObject w=new JSONObject().put("profile","ege_base").put("pages",new JSONArray().put(new JSONObject().put("kind","answers").put("reviewed",true)));try{Exports.validate(w);fail();}catch(java.io.IOException expected){}}
 @Test public void csvInjectionGuard(){assertEquals("\"'=1+1\"",Exports.csv("=1+1"));assertEquals("\"Тест\"",Exports.csv("Тест"));}
 @Test public void unknownSheetNotPupil()throws Exception{assertFalse(Exports.answer(new JSONObject().put("kind","unknown")));}
 @Test public void unknownSheetBlocksExport()throws Exception{JSONObject w=new JSONObject().put("profile","oge_math").put("pages",new JSONArray().put(new JSONObject().put("kind","unknown")));try{Exports.validate(w);fail();}catch(java.io.IOException expected){assertTrue(expected.getMessage().contains("тип листа"));}}
 @Test public void extraSheetMustBeViewed()throws Exception{JSONObject w=new JSONObject().put("profile","oge_math").put("pages",new JSONArray().put(new JSONObject().put("kind","manual")));try{Exports.validate(w);fail();}catch(java.io.IOException expected){assertTrue(expected.getMessage().contains("дополнительный"));}}
 @Test public void mismatchedExamRejected()throws Exception{JSONObject w=new JSONObject().put("profile","ege_base").put("pages",new JSONArray().put(new JSONObject().put("kind","oge").put("reviewed",true)));try{Exports.validate(w);fail();}catch(java.io.IOException expected){assertTrue(expected.getMessage().contains("не соответствует"));}}
}
