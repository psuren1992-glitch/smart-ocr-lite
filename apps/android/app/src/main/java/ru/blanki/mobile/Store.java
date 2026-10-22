package ru.blanki.mobile;

import android.content.Context;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class Store {
    public final File root;
    public Store(Context c){root=new File(c.getFilesDir(),"works");root.mkdirs();}
    public File dir(String id)throws IOException {if(!id.matches("[a-f0-9]{32}"))throw new IOException("Неверный идентификатор");return new File(root,id);}
    public static String id(){return UUID.randomUUID().toString().replace("-","");}
    public JSONObject create(String title,String profile)throws Exception{
        if(!Arrays.asList(Profile.IDS).contains(profile))throw new IOException("Неизвестный профиль");
        JSONObject w=new JSONObject().put("id",id()).put("title",title).put("profile",profile).put("pages",new JSONArray()).put("keys",new JSONObject()).put("created",System.currentTimeMillis());
        dir(w.getString("id")).mkdirs();save(w);return w;
    }
    public void save(JSONObject work)throws Exception{
        File directory=dir(work.getString("id"));directory.mkdirs();
        AtomicFile target=new AtomicFile(new File(directory,"work.json"));FileOutputStream out=null;
        try{out=target.startWrite();out.write(work.toString().getBytes(StandardCharsets.UTF_8));target.finishWrite(out);}catch(Exception e){if(out!=null)target.failWrite(out);throw e;}
    }
    public JSONObject load(String id)throws Exception{
        AtomicFile f=new AtomicFile(new File(dir(id),"work.json"));JSONObject work=new JSONObject(new String(f.readFully(),StandardCharsets.UTF_8));
        return PageDeletion.recover(dir(id),work,this::save);
    }
    public List<JSONObject> list()throws Exception{
        List<JSONObject> out=new ArrayList<>();File[] dirs=root.listFiles();if(dirs!=null)for(File d:dirs)if(d.isDirectory()&&d.getName().matches("[a-f0-9]{32}"))out.add(load(d.getName()));
        out.sort((a,b)->Long.compare(b.optLong("created"),a.optLong("created")));return out;
    }
    public File pageDir(JSONObject work,JSONObject page)throws Exception{PageEdits.requireId(page.getString("id"));File d=new File(dir(work.getString("id")),page.getString("id"));d.mkdirs();return d;}
    public JSONObject deletePages(JSONObject work,Set<String> ids)throws Exception {
        return PageDeletion.remove(dir(work.getString("id")),work,ids,this::save);
    }
    public static void copy(InputStream in,File file,long limit)throws IOException{
        try(in;OutputStream out=new FileOutputStream(file)){byte[] b=new byte[65536];long n=0;int r;while((r=in.read(b))!=-1){n+=r;if(n>limit)throw new IOException("Файл слишком большой");out.write(b,0,r);}}
    }
    public JSONObject add(JSONObject work)throws Exception{
        JSONObject p=new JSONObject().put("id",id()).put("kind","unknown").put("name","").put("variant","").put("school","").put("reviewed",false).put("answers",new JSONObject()).put("raw",new JSONObject()).put("manual",new JSONObject());
        pageDir(work,p);return p;
    }
}
