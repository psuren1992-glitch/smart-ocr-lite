package ru.blanki.mobile;

import org.junit.*;
import org.json.*;
import java.io.IOException;
import java.util.*;
import static org.junit.Assert.*;

public class PageEditsTest {
    static String id(int n){return String.format(Locale.ROOT,"%032x",n);}
    static JSONObject page(int n,String kind)throws Exception {
        return new JSONObject().put("id",id(n)).put("kind",kind).put("name","ТЕСТ "+n)
            .put("variant","1").put("school","123456").put("reviewed",true)
            .put("answers",new JSONObject().put("1","-0,68"));
    }
    static JSONObject work(String profile,JSONObject... pages)throws Exception {
        return new JSONObject().put("id",id(999)).put("profile",profile).put("title","QA")
            .put("keys",new JSONObject().put("1",new JSONObject().put("1","-0,68")))
            .put("pages",new JSONArray(Arrays.asList(pages)));
    }
    @Test public void onePageRemovedWithoutMutatingOriginal()throws Exception {
        JSONObject original=work("oge_math",page(1,"oge"),page(2,"oge"),page(3,"oge"));String before=original.toString();
        JSONObject result=PageEdits.remove(original,Set.of(id(2)));
        assertEquals(before,original.toString());assertEquals(2,result.getJSONArray("pages").length());
        assertEquals(id(3),result.getJSONArray("pages").getJSONObject(1).getString("id"));
        assertTrue(result.getJSONArray("pages").getJSONObject(1).getBoolean("reviewed"));
        assertEquals("-0,68",result.getJSONObject("keys").getJSONObject("1").getString("1"));
    }
    @Test public void multipleIdsNotShiftingIndices()throws Exception {
        JSONObject result=PageEdits.remove(work("oge_math",page(1,"oge"),page(2,"oge"),page(3,"oge"),page(4,"oge")),Set.of(id(1),id(3)));
        assertEquals(id(2),result.getJSONArray("pages").getJSONObject(0).getString("id"));
        assertEquals(id(4),result.getJSONArray("pages").getJSONObject(1).getString("id"));
    }
    @Test public void allPagesMayBeRemovedButKeysStay()throws Exception {
        JSONObject result=PageEdits.remove(work("oge_math",page(1,"oge")),Set.of(id(1)));
        assertEquals(0,result.getJSONArray("pages").length());assertTrue(result.getJSONObject("keys").has("1"));
        try{Exports.validate(result);fail();}catch(IOException expected){assertTrue(expected.getMessage().contains("Нет бланков"));}
    }
    @Test public void registrationRemovalRequiresBindingReview()throws Exception {
        JSONObject result=PageEdits.remove(work("ege_base",page(1,"registration"),page(2,"answers"),page(3,"registration"),page(4,"answers")),Set.of(id(3)));
        JSONObject affected=result.getJSONArray("pages").getJSONObject(2);
        assertTrue(affected.getBoolean("registration_link_invalid"));assertFalse(affected.getBoolean("reviewed"));
        assertEquals("ТЕСТ 4",affected.getString("name"));assertEquals("-0,68",affected.getJSONObject("answers").getString("1"));
        assertTrue(result.getJSONArray("pages").getJSONObject(1).getBoolean("reviewed"));
    }
    @Test public void deletedAnswerAndNextRegistrationCannotSilentlyRebind()throws Exception {
        JSONObject result=PageEdits.remove(work("ege_base",page(1,"registration"),page(2,"answers"),page(3,"registration"),page(4,"answers")),Set.of(id(2),id(3)));
        JSONObject answer=result.getJSONArray("pages").getJSONObject(1);
        assertTrue(answer.getBoolean("registration_link_invalid"));answer.put("reviewed",true);
        try{Exports.validate(result);fail();}catch(IOException expected){assertTrue(expected.getMessage().contains("принадлежность"));}
    }
    @Test public void removingWholeEarlierPacketDoesNotResetNext()throws Exception {
        JSONObject result=PageEdits.remove(work("ege_base",page(1,"registration"),page(2,"answers"),page(3,"registration"),page(4,"answers")),Set.of(id(1),id(2)));
        assertTrue(result.getJSONArray("pages").getJSONObject(1).getBoolean("reviewed"));
        assertFalse(result.getJSONArray("pages").getJSONObject(1).optBoolean("registration_link_invalid"));
    }
    @Test public void orphanedOgeAdditionalSheetNeedsReview()throws Exception {
        JSONObject result=PageEdits.remove(work("oge_math",page(1,"oge"),page(2,"manual"),page(3,"oge")),Set.of(id(1)));
        JSONObject extra=result.getJSONArray("pages").getJSONObject(0);
        assertTrue(extra.getBoolean("attachment_review_required"));assertFalse(extra.getBoolean("reviewed"));
        assertTrue(result.getJSONArray("pages").getJSONObject(1).getBoolean("reviewed"));
    }
    @Test public void deletingAdditionalSheetDoesNotInvalidateAnswers()throws Exception {
        JSONObject result=PageEdits.remove(work("oge_math",page(1,"oge"),page(2,"manual"),page(3,"manual")),Set.of(id(2)));
        assertTrue(result.getJSONArray("pages").getJSONObject(0).getBoolean("reviewed"));
        assertTrue(result.getJSONArray("pages").getJSONObject(1).getBoolean("reviewed"));
    }
    @Test public void unknownIdsRejected()throws Exception {
        try{PageEdits.remove(work("oge_math",page(1,"oge")),Set.of(id(2)));fail();}catch(IOException expected){}
    }
    @Test public void pathTraversalRejected()throws Exception {
        try{PageEdits.remove(work("oge_math",page(1,"oge")),Set.of("../other"));fail();}catch(IOException expected){}
    }
    @Test public void emptySelectionRejected()throws Exception {
        try{PageEdits.remove(work("oge_math",page(1,"oge")),Collections.emptySet());fail();}catch(IOException expected){}
    }
    @Test public void oldPendingDeletionPreserved()throws Exception {
        JSONObject w=work("oge_math",page(1,"oge"));w.put(PageEdits.PENDING,new JSONArray().put(id(5)));
        JSONObject result=PageEdits.remove(w,Set.of(id(1)));assertEquals(2,result.getJSONArray(PageEdits.PENDING).length());
    }
}
