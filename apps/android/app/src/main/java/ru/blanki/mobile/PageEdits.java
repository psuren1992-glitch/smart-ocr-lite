package ru.blanki.mobile;

import org.json.*;
import java.io.IOException;
import java.util.*;

/** Pure transformations: never mutate the open work before its replacement is saved. */
public final class PageEdits {
    public static final String PENDING="pending_page_deletions";

    public static void requireId(String id)throws IOException {
        if(id==null||!id.matches("[a-f0-9]{32}"))throw new IOException("Неверный идентификатор листа");
    }

    public static JSONObject remove(JSONObject work,Set<String> selected)throws Exception {
        if(selected==null||selected.isEmpty())throw new IOException("Выберите хотя бы один лист");
        JSONObject next=new JSONObject(work.toString());
        JSONArray pages=next.getJSONArray("pages"),kept=new JSONArray();
        Set<String> found=new HashSet<>(),all=new HashSet<>();
        for(String id:selected)requireId(id);
        for(int i=0;i<pages.length();i++) {
            JSONObject page=pages.getJSONObject(i);String id=page.getString("id");requireId(id);
            if(!all.add(id))throw new IOException("Повторный идентификатор листа");
            if(selected.contains(id))found.add(id);else kept.put(page);
        }
        if(!found.equals(selected))throw new IOException("Список листов изменился. Выберите листы заново.");
        next.put("pages",kept);
        invalidateChangedLinks(work,next);
        Set<String> pending=new LinkedHashSet<>();
        JSONArray old=work.optJSONArray(PENDING);
        if(old!=null)for(int i=0;i<old.length();i++)pending.add(old.getString(i));
        pending.addAll(selected);next.put(PENDING,new JSONArray(pending));
        return next;
    }

    public static JSONObject registrationFor(JSONArray pages,String answerId)throws Exception {
        JSONObject registration=null;
        for(int i=0;i<pages.length();i++) {
            JSONObject page=pages.getJSONObject(i);
            if(page.getString("id").equals(answerId))return registration;
            if(page.optString("kind").equals("registration"))registration=page;
            else if(Exports.answer(page))registration=null;
        }
        return null;
    }

    static Map<String,String> contexts(JSONArray pages)throws Exception {
        Map<String,String> out=new HashMap<>();String registration="",attachment="";
        for(int i=0;i<pages.length();i++) {
            JSONObject page=pages.getJSONObject(i);String id=page.getString("id"),kind=page.optString("kind");
            if(kind.equals("registration")){registration=id;attachment=id;}
            else if(Exports.answer(page)){out.put(id,registration);registration="";attachment=id;}
            else if(kind.equals("manual"))out.put(id,attachment);
        }
        return out;
    }

    public static void invalidateChangedLinks(JSONObject before,JSONObject after)throws Exception {
        Map<String,String> old=contexts(before.getJSONArray("pages")),current=contexts(after.getJSONArray("pages"));
        JSONArray pages=after.getJSONArray("pages");
        for(int i=0;i<pages.length();i++) {
            JSONObject page=pages.getJSONObject(i);String id=page.getString("id"),kind=page.optString("kind");
            if(!Objects.equals(old.get(id),current.get(id))) {
                if(kind.equals("answers")&&Profile.ege(after.getString("profile")))
                    page.put("registration_link_invalid",true).put("reviewed",false);
                else if(kind.equals("manual"))page.put("attachment_review_required",true).put("reviewed",false);
            }
        }
    }
}
