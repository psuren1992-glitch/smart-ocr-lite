package ru.blanki.mobile;
import org.junit.Test;
import static org.junit.Assert.*;
public class ProfileTest {
 @Test public void ranges(){assertEquals(21,Profile.end("ege_base"));assertEquals(12,Profile.end("ege_profile"));assertEquals(2,Profile.start("oge_russian"));assertEquals(26,Profile.end("ege_russian"));}
 @Test public void strictMath(){assertEquals(1,Profile.points("oge_math",1,"-0.68","-0,68"));assertEquals(0,Profile.points("oge_math",1,"0968","-0,68"));assertEquals(0,Profile.points("oge_math",1,"3,2","32"));assertEquals(0,Profile.points("oge_math",1,"01","1"));}
 @Test public void textAndMultisets(){assertEquals(1,Profile.points("oge_russian",2,"321","123"));assertEquals(0,Profile.points("oge_russian",2,"1123","123"));assertEquals(1,Profile.points("oge_russian",9,"СЛОВО","слово"));assertEquals(0,Profile.points("oge_russian",9,"СЛОВА","СЛОВО"));}
 @Test public void partialRussian(){assertEquals(2,Profile.points("ege_russian",8,"12345","12345"));assertEquals(1,Profile.points("ege_russian",8,"123","12345"));assertEquals(0,Profile.points("ege_russian",8,"123456","12345"));}
 @Test public void variants(){assertEquals("6",Profile.variant("06"));assertEquals("",Profile.variant("В6"));assertEquals("",Profile.variant("999"));}
}
