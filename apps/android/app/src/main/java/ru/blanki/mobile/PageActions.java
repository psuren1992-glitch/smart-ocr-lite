package ru.blanki.mobile;

import android.app.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.function.Consumer;

final class PageActions {
    private final Activity activity;
    private final JSONObject work;
    private final Consumer<Set<String>> onDelete;
    PageActions(Activity activity,JSONObject work,Consumer<Set<String>> onDelete){this.activity=activity;this.work=work;this.onDelete=onDelete;}

    void choose()throws Exception {
        JSONArray pages=work.getJSONArray("pages");String[] labels=new String[pages.length()],ids=new String[pages.length()];
        boolean[] checked=new boolean[pages.length()];Set<String> selected=new LinkedHashSet<>();
        for(int i=0;i<pages.length();i++){JSONObject p=pages.getJSONObject(i);ids[i]=p.getString("id");labels[i]=label(i,p);}
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("Какие листы удалить?")
            .setMultiChoiceItems(labels,checked,(d,index,value)->{
                if(value)selected.add(ids[index]);else selected.remove(ids[index]);
                AlertDialog alert=(AlertDialog)d;alert.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(!selected.isEmpty());
                alert.getButton(AlertDialog.BUTTON_NEUTRAL).setText(selected.size()==ids.length?"Снять выбор":"Выбрать все");
                alert.setTitle("Выбрано листов: "+selected.size());
            }).setPositiveButton("Далее",null).setNegativeButton("Отмена",null).setNeutralButton("Выбрать все",null).create();
        dialog.show();dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v->{
            boolean all=selected.size()!=ids.length;selected.clear();
            for(int i=0;i<ids.length;i++){checked[i]=all;dialog.getListView().setItemChecked(i,all);if(all)selected.add(ids[i]);}
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setText(all?"Снять выбор":"Выбрать все");
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(!selected.isEmpty());dialog.setTitle("Выбрано листов: "+selected.size());
        });
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{dialog.dismiss();confirm(selected);});
    }

    void single(String id){confirm(new LinkedHashSet<>(Collections.singletonList(id)));}
    private String label(int index,JSONObject page){return "Лист "+(index+1)+" · "+MainActivity.kindLabel(page.optString("kind"))+(page.optString("name").isEmpty()?"":"\n"+page.optString("name"));}

    private void confirm(Set<String> ids) {
        try {
            JSONObject preview=PageEdits.remove(work,ids);StringBuilder message=new StringBuilder();JSONArray pages=work.getJSONArray("pages");
            for(int i=0;i<pages.length();i++)if(ids.contains(pages.getJSONObject(i).getString("id")))message.append(label(i,pages.getJSONObject(i))).append('\n');
            message.append("\nИз этой работы будут удалены выбранные сканы, их распознавание и правки. Исходные PDF и фотографии вне приложения не изменятся. Отменить удаление нельзя.");
            if(preview.getJSONArray("pages").length()==0)message.append("\n\nРабота останется пустой; название и ключ ответов сохранятся.");
            else message.append("\n\nЕсли изменится состав комплекта, оставшиеся связанные листы потребуется сверить заново.");
            AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("Удалить листов: "+ids.size()+"?").setMessage(message)
                .setNegativeButton("Оставить",null).setPositiveButton("Удалить",(d,w)->onDelete.accept(new LinkedHashSet<>(ids))).create();
            dialog.show();dialog.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(MainActivity.RED);
        }catch(Exception e){new AlertDialog.Builder(activity).setMessage(e.getMessage()).setPositiveButton("Понятно",null).show();}
    }
}
