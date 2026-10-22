package ru.blanki.mobile;

import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class Exports {
    public static boolean answer(JSONObject p){return p.optString("kind").equals("oge")||p.optString("kind").equals("answers");}
    public static JSONObject key(JSONObject work,JSONObject page){return work.optJSONObject("keys").optJSONObject(Profile.variant(page.optString("variant")));}
    public static String score(JSONObject work,JSONObject page)throws Exception{
        if(!page.optBoolean("reviewed"))return "Не сверено";JSONObject key=key(work,page);if(key==null)return "Нет ключа";
        String profile=work.getString("profile");int points=0,total=0,missing=0;
        for(int t=Profile.start(profile);t<=Profile.end(profile);t++){if(key.optString(""+t).isEmpty()){missing++;continue;}points+=Profile.points(profile,t,page.getJSONObject("answers").optString(""+t),key.optString(""+t));total+=Profile.max(profile,t);}
        return points+" / "+total+(missing>0?" · нет ключа к "+missing+" заданиям":"");
    }
    public static void validate(JSONObject w)throws Exception{
        int count=0;JSONArray pages=w.getJSONArray("pages");
        for(int i=0;i<pages.length();i++){
            JSONObject p=pages.getJSONObject(i);String kind=p.optString("kind");
            if(!Arrays.asList("oge","answers","registration","manual").contains(kind))throw new IOException("Сначала выберите тип листа "+(i+1));
            if(Profile.ege(w.getString("profile"))?kind.equals("oge"):kind.equals("answers")||kind.equals("registration"))throw new IOException("Тип листа "+(i+1)+" не соответствует экзамену");
            if(kind.equals("manual")&&!p.optBoolean("reviewed"))throw new IOException("Сначала просмотрите дополнительный лист "+(i+1));
            if(kind.equals("answers")&&p.optBoolean("registration_link_invalid"))throw new IOException("Подтвердите принадлежность листа "+(i+1)+" после изменения комплекта");
        }
        for(int i=0;i<pages.length();i++){JSONObject p=pages.getJSONObject(i);if(answer(p)){count++;if(!p.optBoolean("reviewed"))throw new IOException("Сначала сверьте лист "+(i+1));if(Profile.ege(w.getString("profile"))){JSONObject reg=null;for(int j=i-1;j>=0;j--){JSONObject q=pages.getJSONObject(j);if(q.optString("kind").equals("registration")){reg=q;break;}if(answer(q))break;}if(reg==null||!reg.optBoolean("reviewed"))throw new IOException("Перед листом "+(i+1)+" нужна сверенная регистрация");}}}
        if(count==0)throw new IOException("Нет бланков ответов №1");
    }
    static String csv(String s){if(!s.isEmpty()&&"=+-@".indexOf(s.charAt(0))>=0)s="'"+s;return "\""+s.replace("\"","\"\"")+"\"";}
    public static File csv(JSONObject w,File output)throws Exception{
        validate(w);String p=w.getString("profile");StringBuilder s=new StringBuilder("\uFEFFЛист;ФИО;Вариант;Код школы;Часть 1\r\n");JSONArray pages=w.getJSONArray("pages");
        for(int i=0;i<pages.length();i++){JSONObject a=pages.getJSONObject(i);if(!answer(a))continue;s.append(i+1).append(';').append(csv(a.optString("name"))).append(';').append(csv(a.optString("variant"))).append(';').append(csv(a.optString("school"))).append(';').append(csv(score(w,a))).append("\r\n");}
        s.append("\r\nЛист;ФИО;№ задания;Прочитано;Верный ответ;Макс. балл;Баллы\r\n");
        for(int i=0;i<pages.length();i++){JSONObject a=pages.getJSONObject(i);if(!answer(a))continue;JSONObject key=key(w,a);
            for(int t=Profile.start(p);t<=Profile.end(p);t++){String got=a.getJSONObject("answers").optString(""+t),expected=key==null?"":key.optString(""+t);s.append(i+1).append(';').append(csv(a.optString("name"))).append(';').append(t).append(';').append(csv(got)).append(';').append(csv(expected)).append(';').append(Profile.max(p,t)).append(';').append(expected.isEmpty()?"":Profile.points(p,t,got,expected)).append("\r\n");}
        }
        try(OutputStream out=new FileOutputStream(output)){out.write(s.toString().getBytes(StandardCharsets.UTF_8));}return output;
    }
    public static File pdf(JSONObject w,Store store,File output)throws Exception{
        validate(w);String profile=w.getString("profile");Paint paint=new Paint(3);paint.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));
        PdfDocument pdf=new PdfDocument();try{
            int n=1;JSONArray pages=w.getJSONArray("pages");for(int i=0;i<pages.length();i++){JSONObject a=pages.getJSONObject(i);
                if(answer(a)){
                    PdfDocument.Page pg=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,n++).create());Canvas c=pg.getCanvas();paint.setColor(0xFF183D32);paint.setTextSize(20);c.drawText("Бланки · "+Profile.label(profile),30,40,paint);paint.setTextSize(14);c.drawText(a.optString("name"),30,70,paint);c.drawText("Лист "+(i+1)+" · Вариант "+a.optString("variant")+" · "+score(w,a),30,94,paint);paint.setTextSize(11);c.drawText("№          Ответ ученика                    Ключ                    Баллы",30,130,paint);
                    JSONObject key=key(w,a);int y=155;for(int t=Profile.start(profile);t<=Profile.end(profile);t++){String got=a.getJSONObject("answers").optString(""+t),expected=key==null?"":key.optString(""+t);c.drawText(""+t,30,y,paint);c.drawText(shorten(got,25),80,y,paint);c.drawText(shorten(expected,25),300,y,paint);c.drawText(expected.isEmpty()?"нет ключа":""+Profile.points(profile,t,got,expected)+"/"+Profile.max(profile,t),490,y,paint);y+=20;}
                    c.drawText("Развёрнутые решения проверяет учитель. Это не итоговая отметка.",30,790,paint);pdf.finishPage(pg);
                }
                File d=store.pageDir(w,a),scan=new File(d,"scan.jpg");if(!scan.isFile())scan=new File(d,"original.jpg");if(!scan.isFile())continue;
                Bitmap bitmap=ImageTools.load(scan,2400);try{
                    PdfDocument.Page pg=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,n++).create());Canvas c=pg.getCanvas();paint.setTextSize(12);c.drawText("Исходный лист "+(i+1)+" · "+a.optString("kind"),25,25,paint);
                    float scale=Math.min(545f/bitmap.getWidth(),770f/bitmap.getHeight());float width=bitmap.getWidth()*scale,height=bitmap.getHeight()*scale;c.drawBitmap(bitmap,null,new RectF((595-width)/2,45,(595+width)/2,45+height),paint);pdf.finishPage(pg);
                }finally{bitmap.recycle();}
            }
            try(OutputStream out=new FileOutputStream(output)){pdf.writeTo(out);}
        }finally{pdf.close();}return output;
    }
    static String shorten(String s,int max){return s.length()<=max?s:s.substring(0,max-1)+"…";}
}
