package ru.blanki.mobile;

import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;

public final class PageDeletion {
    public interface Saver {void save(JSONObject work)throws Exception;}
    interface Remover {void remove(Path directory)throws IOException;}

    public static JSONObject remove(File directory,JSONObject work,Set<String> ids,Saver saver)throws Exception {
        JSONObject next=PageEdits.remove(work,ids);
        validatePending(directory,next);
        // The durable tombstone comes first. A crash can leave extra files, never a live broken page.
        saver.save(next);
        try{return recover(directory,next,saver,PageDeletion::eraseTree);}
        catch(Exception e){return next;}
    }

    public static JSONObject recover(File directory,JSONObject work,Saver saver)throws Exception {
        return recover(directory,work,saver,PageDeletion::eraseTree);
    }

    static JSONObject recover(File directory,JSONObject work,Saver saver,Remover remover)throws Exception {
        JSONArray pending=work.optJSONArray(PageEdits.PENDING);
        if(pending==null||pending.length()==0)return work;
        List<Path> paths=validatePending(directory,work);JSONArray remaining=new JSONArray();
        for(int i=0;i<paths.size();i++) {
            try {remover.remove(paths.get(i));}
            catch(IOException|SecurityException e){remaining.put(pending.getString(i));}
        }
        JSONObject cleaned=new JSONObject(work.toString());
        if(remaining.length()==0)cleaned.remove(PageEdits.PENDING);else cleaned.put(PageEdits.PENDING,remaining);
        try {saver.save(cleaned);return cleaned;}
        catch(Exception e){return work;}
    }

    static List<Path> validatePending(File directory,JSONObject work)throws Exception {
        Path root=directory.getCanonicalFile().toPath();Set<String> live=new HashSet<>(),seen=new HashSet<>();
        JSONArray pages=work.getJSONArray("pages"),pending=work.getJSONArray(PageEdits.PENDING);
        for(int i=0;i<pages.length();i++)live.add(pages.getJSONObject(i).getString("id"));
        List<Path> result=new ArrayList<>();
        for(int i=0;i<pending.length();i++) {
            String id=pending.getString(i);PageEdits.requireId(id);
            if(live.contains(id)||!seen.add(id))throw new IOException("Удаление пересекается с существующим листом");
            Path path=root.resolve(id).normalize();
            if(!path.getParent().equals(root)||Files.isSymbolicLink(path)
                ||!path.toFile().getCanonicalFile().toPath().getParent().equals(root))
                throw new IOException("Нельзя удалить каталог за пределами работы");
            result.add(path);
        }
        return result;
    }

    static void eraseTree(Path directory)throws IOException {
        if(!Files.exists(directory,LinkOption.NOFOLLOW_LINKS))return;
        Files.walkFileTree(directory,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes attrs)throws IOException {
                // walkFileTree does not follow symbolic links, including links in OCR staging folders.
                Files.delete(file);return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult postVisitDirectory(Path dir,IOException error)throws IOException {
                if(error!=null)throw error;Files.delete(dir);return FileVisitResult.CONTINUE;
            }
        });
    }
}
