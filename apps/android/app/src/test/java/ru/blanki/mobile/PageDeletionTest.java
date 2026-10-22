package ru.blanki.mobile;

import org.junit.*;
import org.junit.rules.TemporaryFolder;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import static org.junit.Assert.*;
import static ru.blanki.mobile.PageEditsTest.*;

public class PageDeletionTest {
    @Rule public TemporaryFolder temp=new TemporaryFolder();
    File root;
    @Before public void setup()throws Exception{root=temp.newFolder("work");}
    File scan(int n)throws Exception {
        File folder=new File(root,id(n));assertTrue(folder.mkdirs());File file=new File(folder,"scan.jpg");
        Files.write(file.toPath(),new byte[]{1,2,3});return file;
    }
    @Test public void commitFailureNeverDeletesFiles()throws Exception {
        File scan=scan(1);JSONObject w=work("oge_math",page(1,"oge"));
        try{PageDeletion.remove(root,w,Set.of(id(1)),next->{throw new IOException("disk full");});fail();}catch(IOException expected){}
        assertTrue(scan.exists());assertEquals(1,w.getJSONArray("pages").length());
    }
    @Test public void commitComesBeforePhysicalRemoval()throws Exception {
        File removed=scan(1),kept=scan(2);List<JSONObject> saved=new ArrayList<>();
        JSONObject result=PageDeletion.remove(root,work("oge_math",page(1,"oge"),page(2,"oge")),Set.of(id(1)),next->{
            if(saved.isEmpty()){assertTrue(removed.exists());assertTrue(next.has(PageEdits.PENDING));}
            saved.add(new JSONObject(next.toString()));
        });
        assertFalse(removed.exists());assertTrue(kept.exists());assertEquals(2,saved.size());assertFalse(result.has(PageEdits.PENDING));
    }
    @Test public void interruptedDeletionCanResume()throws Exception {
        File removed=scan(1);JSONObject pending=PageEdits.remove(work("oge_math",page(1,"oge")),Set.of(id(1)));
        JSONObject result=PageDeletion.recover(root,pending,next->{});
        assertFalse(removed.exists());assertFalse(result.has(PageEdits.PENDING));
    }
    @Test public void lockedFilesRemainPending()throws Exception {
        File file=scan(1);JSONObject pending=PageEdits.remove(work("oge_math",page(1,"oge")),Set.of(id(1)));
        JSONObject result=PageDeletion.recover(root,pending,next->{},path->{throw new IOException("locked");});
        assertTrue(file.exists());assertEquals(id(1),result.getJSONArray(PageEdits.PENDING).getString(0));
    }
    @Test public void cleanupSaveFailureKeepsDurableTombstone()throws Exception {
        File file=scan(1);JSONObject pending=PageEdits.remove(work("oge_math",page(1,"oge")),Set.of(id(1)));
        JSONObject result=PageDeletion.recover(root,pending,next->{throw new IOException("disk full");});
        assertFalse(file.exists());assertTrue(result.has(PageEdits.PENDING));
        assertFalse(PageDeletion.recover(root,result,next->{}).has(PageEdits.PENDING));
    }
    @Test public void pendingCannotEraseLivePage()throws Exception {
        File file=scan(1);JSONObject w=work("oge_math",page(1,"oge"));w.put(PageEdits.PENDING,new JSONArray().put(id(1)));
        try{PageDeletion.recover(root,w,next->{});fail();}catch(IOException expected){}
        assertTrue(file.exists());
    }
    @Test public void siblingOutsidePageIsUntouched()throws Exception {
        File file=scan(1),outside=temp.newFile("outside.pdf");Files.write(outside.toPath(),new byte[]{5});
        PageDeletion.remove(root,work("oge_math",page(1,"oge")),Set.of(id(1)),next->{});
        assertFalse(file.exists());assertTrue(outside.exists());assertEquals(5,Files.readAllBytes(outside.toPath())[0]);
    }
    @Test public void unsafePendingPathsRejectedBeforeCleanup()throws Exception {
        File file=scan(1);JSONObject w=work("oge_math");w.put(PageEdits.PENDING,new JSONArray().put(id(1)).put("../outside"));
        try{PageDeletion.recover(root,w,next->{});fail();}catch(IOException expected){}
        assertTrue(file.exists());
    }
}
