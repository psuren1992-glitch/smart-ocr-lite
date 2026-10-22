package ru.blanki.mobile;

import java.io.*;
import java.util.*;
import java.util.zip.*;
import java.nio.charset.StandardCharsets;
import org.json.*;
import org.xmlpull.v1.*;
import android.util.Xml;

public final class MaskReader {
    public static List<List<String>> csv(String text)throws IOException{
        text=text.replace("\uFEFF","");String first=text.split("\\r?\\n",2)[0];char separator=first.contains(";")?';':first.contains("\t")?'\t':',';
        List<List<String>> rows=new ArrayList<>();List<String> row=new ArrayList<>();StringBuilder cell=new StringBuilder();boolean quote=false;
        for(int i=0;i<text.length();i++){char c=text.charAt(i);
            if(c=='"'){if(quote&&i+1<text.length()&&text.charAt(i+1)=='"'){cell.append('"');i++;}else quote=!quote;}
            else if(!quote&&(c==separator||c=='\n')){row.add(cell.toString().trim());cell.setLength(0);if(c=='\n'){rows.add(row);row=new ArrayList<>();}}
            else if(c!='\r')cell.append(c);
        }
        if(quote)throw new IOException("Незакрытая кавычка CSV");
        if(cell.length()>0||!row.isEmpty()){row.add(cell.toString().trim());rows.add(row);}return rows;
    }
    static XmlPullParser xml(byte[] bytes)throws Exception{
        String value=new String(bytes,StandardCharsets.UTF_8);
        if(value.toUpperCase(Locale.ROOT).contains("<!DOCTYPE")||value.toUpperCase(Locale.ROOT).contains("<!ENTITY"))throw new IOException("Внешние сущности XML запрещены");
        XmlPullParser p=Xml.newPullParser();p.setInput(new StringReader(value));return p;
    }
    public static List<List<String>> xlsx(InputStream stream)throws Exception{
        Map<String,byte[]> files=new HashMap<>();long total=0;int entries=0;
        try(ZipInputStream z=new ZipInputStream(stream)){
            ZipEntry e;byte[] b=new byte[8192];while((e=z.getNextEntry())!=null){
                if(++entries>1000)throw new IOException("Слишком много файлов XLSX");
                String n=e.getName();if(n.contains("..")||n.startsWith("/")||files.containsKey(n))throw new IOException("Неверная структура XLSX");
                ByteArrayOutputStream out=new ByteArrayOutputStream();int r;while((r=z.read(b))!=-1){total+=r;if(total>16*1024*1024)throw new IOException("XLSX слишком большой");out.write(b,0,r);}files.put(n,out.toByteArray());
            }
        }
        List<String> strings=new ArrayList<>();if(files.containsKey("xl/sharedStrings.xml")){
            XmlPullParser p=xml(files.get("xl/sharedStrings.xml"));StringBuilder s=null;
            for(int t=p.getEventType();t!=XmlPullParser.END_DOCUMENT;t=p.next()){
                if(t==XmlPullParser.START_TAG&&p.getName().equals("si"))s=new StringBuilder();
                else if(t==XmlPullParser.START_TAG&&p.getName().equals("t")&&s!=null)s.append(p.nextText());
                else if(t==XmlPullParser.END_TAG&&p.getName().equals("si")){strings.add(s.toString());s=null;}
            }
        }
        if(!files.containsKey("xl/worksheets/sheet1.xml"))throw new IOException("В XLSX нет первого листа");
        XmlPullParser p=xml(files.get("xl/worksheets/sheet1.xml"));List<List<String>> rows=new ArrayList<>();List<String> row=null;int col=0;String type="",value="";boolean formula=false;
        for(int t=p.getEventType();t!=XmlPullParser.END_DOCUMENT;t=p.next()){
            if(t==XmlPullParser.START_TAG){switch(p.getName()){
                case "row":row=new ArrayList<>();break;
                case "c":String ref=p.getAttributeValue(null,"r");col=0;if(ref!=null)for(char c:ref.toCharArray()){if(c<'A'||c>'Z')break;col=col*26+c-'A'+1;}col=Math.max(0,col-1);if(col>100)throw new IOException("Слишком много колонок");type=p.getAttributeValue(null,"t");value="";formula=false;break;
                case "f":formula=true;break;
                case "v":case "t":value+=p.nextText();break;
            }}else if(t==XmlPullParser.END_TAG&&p.getName().equals("c")&&row!=null){
                if(formula)throw new IOException("В маске нужны значения, не формулы");
                if("s".equals(type)){int i=Integer.parseInt(value);if(i<0||i>=strings.size())throw new IOException("Ошибка текста XLSX");value=strings.get(i);}
                while(row.size()<=col)row.add("");row.set(col,value);
            }else if(t==XmlPullParser.END_TAG&&p.getName().equals("row")&&row!=null){rows.add(row);row=null;if(rows.size()>200)throw new IOException("Слишком много строк в маске");}
        }
        return rows;
    }
    public static JSONObject parse(List<List<String>> rows,String profile)throws Exception{
        rows.removeIf(r->r.stream().allMatch(String::isBlank));if(rows.size()<2)throw new IOException("Маска пуста");
        List<String> header=rows.get(0);if(header.size()<2)throw new IOException("Нужны столбцы: № задания; Вариант 1; ...");
        JSONObject keys=new JSONObject();List<String> variants=new ArrayList<>();variants.add("");
        for(int i=1;i<header.size();i++){
            String v=Profile.variant(header.get(i).replaceFirst("(?iu)^вариант\\s*","").trim());
            if(v.isEmpty()||keys.has(v))throw new IOException("Неверный или повторный вариант в столбце "+(i+1));
            variants.add(v);keys.put(v,new JSONObject());
        }
        Set<Integer> seen=new HashSet<>();
        for(int n=1;n<rows.size();n++){
            List<String> r=rows.get(n);int task;
            try{task=Integer.parseInt(r.get(0).replace("№","").trim());}catch(Exception e){throw new IOException("Строка "+(n+1)+": нужен номер задания");}
            if(task<Profile.start(profile)||task>Profile.end(profile)||!seen.add(task))throw new IOException("Строка "+(n+1)+": задание "+task+" вне диапазона или повторяется");
            for(int i=1;i<header.size();i++){
                String value=i<r.size()?r.get(i).trim():"";if(value.length()>200)throw new IOException("Слишком длинный ответ");
                if(Profile.max(profile,task)==2&&!value.isEmpty())for(String option:value.split("\\|"))if(!option.matches("[0-9]{5}"))throw new IOException("Задание "+task+": в ключе должно быть 5 цифр");
                if(!value.isEmpty())keys.getJSONObject(variants.get(i)).put(""+task,value);
            }
        }
        return keys;
    }
}
