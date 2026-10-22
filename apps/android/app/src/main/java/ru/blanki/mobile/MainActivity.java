package ru.blanki.mobile;

import android.app.*;
import android.os.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.graphics.pdf.PdfRenderer;
import android.net.Uri;
import android.provider.MediaStore;
import android.view.*;
import android.widget.*;
import android.text.*;
import androidx.core.content.FileProvider;
import org.json.*;
import org.opencv.android.OpenCVLoader;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class MainActivity extends Activity {
    static final int GREEN=0xFF23634F,INK=0xFF183D32,CREAM=0xFFF4F3EB,RED=0xFFE00020;
    static final int CAMERA=10,IMPORT=11,MASK=12,SAVE_EXPORT=13;
    final ExecutorService worker=Executors.newSingleThreadExecutor();Store store;JSONObject work;LinearLayout body,root;TextView status;
    Ocr ocr;NameVoiceInput voiceInput;String screen="home";int pageIndex=-1;boolean dirty=false,busy=false;volatile boolean cancelled=false;Runnable draftSave;File cameraFile,exportFile;String exportMime;
    interface Job {void run()throws Exception;}
    int dp(float n){return Math.round(n*getResources().getDisplayMetrics().density);}
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);if(!OpenCVLoader.initLocal()){new AlertDialog.Builder(this).setMessage("Не удалось загрузить обработчик изображений").setPositiveButton("Закрыть",(d,w)->finish()).show();return;}store=new Store(this);voiceInput=new NameVoiceInput(this);
        try{if(saved!=null){String id=saved.getString("work");if(id!=null)work=store.load(id);String path=saved.getString("camera");if(path!=null)cameraFile=new File(path);}if(work!=null)showWork();else home();
            if(BuildConfig.DEBUG&&"blank".equals(getIntent().getStringExtra("qa")))qaBlank();
        }catch(Exception e){error(e);}
    }
    @Override protected void onSaveInstanceState(Bundle b){super.onSaveInstanceState(b);if(work!=null)b.putString("work",work.optString("id"));if(cameraFile!=null)b.putString("camera",cameraFile.toString());}
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grants){super.onRequestPermissionsResult(code,permissions,grants);if(voiceInput!=null)voiceInput.permissionResult(code,grants);}
    @Override protected void onStop(){if(voiceInput!=null)voiceInput.cancel();super.onStop();}
    @Override protected void onDestroy(){if(voiceInput!=null)voiceInput.cancel();super.onDestroy();}
    @Override public void onBackPressed(){if(busy)return;if(dirty){new AlertDialog.Builder(this).setMessage("Есть несохранённые правки").setPositiveButton("Сохранить черновик",(d,w)->{if(draftSave!=null)draftSave.run();if(!dirty)back();}).setNegativeButton("Остаться",null).show();return;}back();}
    void back(){try{if(screen.equals("home")){super.onBackPressed();}else if(screen.equals("work"))home();else showWork();}catch(Exception e){error(e);}}
    void shell(String title,String subtitle){
        if(voiceInput!=null)voiceInput.cancel();
        dirty=false;draftSave=null;root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(CREAM);
        root.setOnApplyWindowInsetsListener((v,insets)->{root.setPadding(dp(16),insets.getSystemWindowInsetTop()+dp(8),dp(16),insets.getSystemWindowInsetBottom()+dp(8));return insets;});
        TextView brand=text("БЛАНКИ  /  НА ТЕЛЕФОНЕ",12,GREEN);brand.setLetterSpacing(.12f);root.addView(brand);
        TextView heading=text(title,29,INK);heading.setTypeface(Typeface.create("serif",Typeface.NORMAL));heading.setPadding(0,dp(9),0,dp(4));root.addView(heading);
        if(!subtitle.isEmpty())root.addView(text(subtitle,13,0xFF65786F));
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(0,dp(12),0,dp(24));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);root.requestApplyInsets();
    }
    TextView text(String s,int size,int color){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);t.setPadding(0,dp(4),0,dp(4));return t;}
    TextView note(String s){TextView t=text(s,14,INK);t.setPadding(dp(12),dp(10),dp(12),dp(10));t.setBackground(bg(0xFFE6EDDF));body.addView(t);return t;}
    GradientDrawable bg(int color){GradientDrawable b=new GradientDrawable();b.setColor(color);b.setCornerRadius(dp(12));return b;}
    Button button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setTextSize(15);b.setAllCaps(false);b.setTextColor(GREEN);b.setMinHeight(dp(48));b.setOnClickListener(v->{if(!busy)action.run();});return b;}
    void action(String s,Runnable r){body.addView(button(s,r),new LinearLayout.LayoutParams(-1,-2));}
    EditText input(LinearLayout parent,String hint,String value,boolean numeric){EditText e=new EditText(this);e.setHint(hint);e.setText(value);e.setTextSize(18);e.setSingleLine(true);e.setTextColor(INK);if(numeric)e.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_FLAG_SIGNED|android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);parent.addView(e,new LinearLayout.LayoutParams(-1,dp(54)));return e;}
    void error(Exception e){String m=e.getMessage();new AlertDialog.Builder(this).setTitle("Не получилось завершить").setMessage(m==null?e.getClass().getSimpleName():m).setPositiveButton("Понятно",null).show();}
    void home()throws Exception{
        screen="home";work=null;shell("Мои работы","Без интернета. Сканы и ответы остаются на этом телефоне.");action("+ Новая работа",this::newWork);note("Пилотная версия. Перед подсчётом баллов обязательно сверьте ФИО, вариант, ответы и нижние замены со сканом.");
        List<JSONObject> works=store.list();if(works.isEmpty())note("Начните с одной контрольной: камера или готовый PDF, затем сверка и ключ ответов.");
        for(JSONObject w:works){Button b=button(w.optString("title")+"\n"+Profile.label(w.optString("profile"))+" · листов: "+w.getJSONArray("pages").length(),()->{try{work=store.load(w.optString("id"));showWork();}catch(Exception e){error(e);}});body.addView(b);}
        action("О приложении и ограничениях",()->new AlertDialog.Builder(this).setTitle("Бланки 0.1 · автономный пилот").setMessage("Android, ARM64. Модель и шаблоны включены в APK. Нет рекламы, учётной записи и сетевого доступа.\n\nСканер: внешняя камера телефона, четыре угла, поворот, фильтры и контраст. Импорт PDF, JPG, PNG. Ключ: первый лист XLSX или CSV, столбцы «№ задания; Вариант 1; ...».\n\nЭто отдельный мобильный движок, не полный ансамбль ПК. ФИО и буквы экспериментальные. Тип каждого листа и принадлежность комплекта подтверждает учитель. Нет автоматического обучения, синхронизации реестра и .blanki. Экспорт: PDF и CSV. Удаление приложения удаляет его внутренние данные.\n\nOpenCV Apache-2.0; ONNX Runtime MIT; модель PaddleOCR Apache-2.0. CamScanner не устанавливался, его код и ресурсы не используются.").setPositiveButton("Закрыть",null).show());
    }
    void newWork(){LinearLayout box=new LinearLayout(this);box.setPadding(dp(20),0,dp(20),0);box.setOrientation(LinearLayout.VERTICAL);EditText title=input(box,"Название контрольной","",false);Spinner profile=new Spinner(this);profile.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,Profile.LABELS));box.addView(profile);new AlertDialog.Builder(this).setTitle("Новая работа").setView(box).setPositiveButton("Создать",(d,w)->{try{String name=title.getText().toString().trim();if(name.isEmpty())name="Контрольная "+new java.text.SimpleDateFormat("dd.MM.yyyy",Locale.ROOT).format(new Date());work=store.create(name,Profile.IDS[profile.getSelectedItemPosition()]);showWork();}catch(Exception e){error(e);}}).setNegativeButton("Отмена",null).show();}
    void showWork()throws Exception{
        screen="work";shell(work.getString("title"),Profile.label(work.getString("profile")));action("+ Снять бланк камерой",this::camera);action("+ Импорт PDF или изображений",()->pick(IMPORT,new String[]{"application/pdf","image/*"},true));action("Ключ ответов · XLSX / CSV / вручную",this::maskMenu);
        JSONArray pages=work.getJSONArray("pages");int count=0,reviewed=0;for(int i=0;i<pages.length();i++){JSONObject p=pages.getJSONObject(i);if(Exports.answer(p)){count++;if(p.optBoolean("reviewed"))reviewed++;}}
        note("Бланков ответов: "+count+" · сверено: "+reviewed+"\nВсего листов: "+pages.length()+". Регистрацию и листы №2 не считаем отдельными учениками.");
        if(Profile.ege(work.getString("profile")))note("Для каждого комплекта: регистрация → ответы №1 → листы №2. Тип листа выбирается вручную в этой версии. Не объединяйте разных учеников без проверки порядка.");
        for(int i=0;i<pages.length();i++){final int index=i;JSONObject p=pages.getJSONObject(i);String title="Лист "+(i+1)+" · "+kindLabel(p.optString("kind"))+"\n"+p.optString("name","");if(Exports.answer(p))title+="\n"+Exports.score(work,p);else title+="\n"+(p.optBoolean("reviewed")?"Сверено":"Нужно просмотреть");body.addView(button(title,()->openPage(index)));}
        if(pages.length()>0){action("Результаты и экспорт",this::results);action("Порядок листов",this::reorder);action("Выбрать и удалить листы",()->{try{new PageActions(this,work,this::deletePages).choose();}catch(Exception e){error(e);}});}
        if(work.optJSONArray(PageEdits.PENDING)!=null)note("Некоторые файлы удалённых листов пока заняты. Приложение повторит очистку при следующем открытии работы.");
        action("Все работы",()->{try{home();}catch(Exception e){error(e);}});
    }
    static String kindLabel(String k){return switch(k){case "registration"->"Регистрация";case "manual"->"Ответы №2 / дополнительный";case "oge","answers"->"Ответы №1";default->"Выберите тип листа";};}
    void deletePages(Set<String> ids){
        JSONObject current=work;
        runBusy("Удаление выбранных листов",()->{
            JSONObject updated=store.deletePages(current,ids);
            for(String extension:new String[]{"pdf","csv"})new File(getCacheDir(),"exports/blanki-"+current.getString("id").substring(0,8)+"."+extension).delete();
            runOnUiThread(()->{try{work=updated;pageIndex=-1;exportFile=null;showWork();Toast.makeText(this,"Удалено листов: "+ids.size(),Toast.LENGTH_LONG).show();}catch(Exception e){error(e);}});
        },false);
    }
    void pick(int code,String[] types,boolean multiple){Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);i.setType("*/*");i.putExtra(Intent.EXTRA_MIME_TYPES,types);i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,multiple);i.addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,code);}
    void camera(){try{File d=new File(getCacheDir(),"camera");d.mkdirs();cameraFile=new File(d,Store.id()+".jpg");Uri uri=FileProvider.getUriForFile(this,getPackageName()+".files",cameraFile);Intent i=new Intent(MediaStore.ACTION_IMAGE_CAPTURE);i.putExtra(MediaStore.EXTRA_OUTPUT,uri);i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);i.setClipData(ClipData.newRawUri("scan",uri));startActivityForResult(i,CAMERA);}catch(Exception e){error(e);}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(result!=RESULT_OK)return;
        try{if(request==CAMERA&&cameraFile!=null){File captured=cameraFile;runBusy("Добавление снимка",()->{try(InputStream in=new FileInputStream(captured)){addImage(in);}runOnUiThread(()->openPage(work.optJSONArray("pages").length()-1));});}
            else if(request==IMPORT&&data!=null){List<Uri> uris=new ArrayList<>();if(data.getClipData()!=null){for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());}else if(data.getData()!=null)uris.add(data.getData());runBusy("Импорт листов",()->{for(Uri uri:uris){if(cancelled)break;importUri(uri);}runOnUiThread(()->{try{showWork();}catch(Exception e){error(e);}});});}
            else if(request==MASK&&data!=null){Uri uri=data.getData();runBusy("Чтение ключа",()->{ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream in=getContentResolver().openInputStream(uri)){byte[] b=new byte[8192];int r;while((r=in.read(b))!=-1){if(bytes.size()+r>4*1024*1024)throw new IOException("Маска больше 4 МиБ");bytes.write(b,0,r);}}byte[] content=bytes.toByteArray();List<List<String>> rows=content.length>2&&content[0]=='P'&&content[1]=='K'?MaskReader.xlsx(new ByteArrayInputStream(content)):MaskReader.csv(new String(content,StandardCharsets.UTF_8));JSONObject keys=MaskReader.parse(rows,work.getString("profile"));runOnUiThread(()->confirmMask(keys));});}
            else if(request==SAVE_EXPORT&&data!=null&&exportFile!=null){Uri uri=data.getData();File f=exportFile;runBusy("Сохранение файла",()->{try(InputStream in=new FileInputStream(f);OutputStream out=getContentResolver().openOutputStream(uri)){byte[] b=new byte[65536];int r;while((r=in.read(b))!=-1)out.write(b,0,r);}runOnUiThread(()->Toast.makeText(this,"Файл сохранён",Toast.LENGTH_LONG).show());});}
        }catch(Exception e){error(e);}}
    void importUri(Uri uri)throws Exception{
        String mime=getContentResolver().getType(uri);File temp=new File(getCacheDir(),Store.id()+".import");Store.copy(getContentResolver().openInputStream(uri),temp,80L*1024*1024);
        boolean pdf="application/pdf".equals(mime);try(RandomAccessFile f=new RandomAccessFile(temp,"r")){if(f.length()>=4)pdf=f.readInt()==0x25504446;}
        if(pdf){try(ParcelFileDescriptor fd=ParcelFileDescriptor.open(temp,ParcelFileDescriptor.MODE_READ_ONLY);PdfRenderer renderer=new PdfRenderer(fd)){
            if(renderer.getPageCount()+work.getJSONArray("pages").length()>100)throw new IOException("В одной работе не более 100 листов");
            for(int i=0;i<renderer.getPageCount();i++){if(cancelled)break;try(PdfRenderer.Page page=renderer.openPage(i)){progress("PDF: лист "+(i+1)+" / "+renderer.getPageCount());float scale=Math.min(3508f/Math.max(page.getWidth(),page.getHeight()),4f);Bitmap bitmap=Bitmap.createBitmap(Math.max(1,(int)(page.getWidth()*scale)),Math.max(1,(int)(page.getHeight()*scale)),Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.WHITE);page.render(bitmap,null,null,PdfRenderer.Page.RENDER_MODE_FOR_PRINT);try{addBitmap(bitmap);}finally{bitmap.recycle();}}}
        }}else try(InputStream in=new FileInputStream(temp)){addImage(in);}
        temp.delete();
    }
    void addImage(InputStream in)throws Exception{File temp=new File(getCacheDir(),Store.id()+".image");Store.copy(in,temp,40L*1024*1024);Bitmap b=ImageTools.load(temp,3508);try{addBitmap(b);}finally{b.recycle();temp.delete();}}
    void addBitmap(Bitmap b)throws Exception{if(work.getJSONArray("pages").length()>=100)throw new IOException("Не более 100 листов в одной работе");JSONObject p=store.add(work);ImageTools.save(b,new File(store.pageDir(work,p),"original.jpg"));ImageTools.save(b,new File(store.pageDir(work,p),"scan.jpg"));work.getJSONArray("pages").put(p);store.save(work);}
    void runBusy(String title,Job job){runBusy(title,job,true);}
    void runBusy(String title,Job job,boolean canCancel){if(busy)return;busy=true;cancelled=false;ProgressDialog dialog=new ProgressDialog(this);dialog.setTitle(title);dialog.setMessage("Выполняется на телефоне…");dialog.setCancelable(false);if(canCancel)dialog.setButton(DialogInterface.BUTTON_NEGATIVE,"Остановить",(d,w)->cancelled=true);dialog.show();status=new TextView(this);activeProgress=dialog;
        worker.submit(()->{try{job.run();}catch(Exception e){runOnUiThread(()->error(e));}finally{runOnUiThread(()->{busy=false;activeProgress=null;dialog.dismiss();});}});
    }
    ProgressDialog activeProgress;
    void progress(String s){if(cancelled)throw new CancellationException("Остановлено. Уже добавленные листы сохранены.");runOnUiThread(()->{if(activeProgress!=null)activeProgress.setMessage(s);});}
    void openPage(int index){try{
        pageIndex=index;JSONObject p=work.getJSONArray("pages").getJSONObject(index);screen="page";shell("Лист "+(index+1),kindLabel(p.optString("kind")));File folder=store.pageDir(work,p);
        image(new File(folder,"scan.jpg"),250);action("Границы, поворот и изображение",()->editScan(index));action("Тип листа: "+kindLabel(p.optString("kind")),()->chooseKind(index));
        Button delete=button("Удалить этот лист",()->new PageActions(this,work,this::deletePages).single(p.optString("id")));delete.setTextColor(RED);body.addView(delete);
        if(p.optString("kind").equals("unknown")){note("Сначала укажите, что на листе. Он пока не считается отдельным учеником.");action("К списку листов",()->{try{showWork();}catch(Exception e){error(e);}});return;}
        if(!p.optString("kind").equals("manual"))action(p.optBoolean("recognized")?"Перераспознать этот лист":"Распознать на телефоне",()->{if(p.optBoolean("recognized")||p.optBoolean("reviewed"))new AlertDialog.Builder(this).setMessage("Повторное распознавание заменит поля этого листа. Продолжить?").setPositiveButton("Перераспознать",(d,w)->recognize(index)).setNegativeButton("Отмена",null).show();else recognize(index);});
        if(p.optBoolean("recognized")||p.optString("kind").equals("manual"))action("Сверить и исправить",()->review(index));
        else action("Внести ответы вручную",()->review(index));action("К списку листов",()->{try{showWork();}catch(Exception e){error(e);}});
    }catch(Exception e){error(e);}}
    void image(File file,int height){if(!file.isFile())return;try{ImageView image=new ImageView(this);Bitmap b=ImageTools.load(file,height>250?2400:1200);image.setImageBitmap(b);image.setAdjustViewBounds(true);image.setScaleType(ImageView.ScaleType.FIT_CENTER);image.setBackground(bg(Color.WHITE));body.addView(image,new LinearLayout.LayoutParams(-1,height==0?-2:dp(height)));image.setOnClickListener(v->fullImage(file));}catch(Exception e){error(e);}}
    void fullImage(File file){try{Bitmap b=ImageTools.load(file,3508);new AlertDialog.Builder(this).setTitle("Скан · масштаб пальцами").setView(new ZoomImage(this,b)).setPositiveButton("Закрыть",(d,w)->b.recycle()).show();}catch(Exception e){error(e);}}
    void chooseKind(int index){try{JSONObject p=work.getJSONArray("pages").getJSONObject(index);boolean ege=Profile.ege(work.getString("profile"));String[] ids=ege?new String[]{"registration","answers","manual"}:new String[]{"oge","manual"};String[] labels=Arrays.stream(ids).map(MainActivity::kindLabel).toArray(String[]::new);new AlertDialog.Builder(this).setTitle("Что на этом листе?").setItems(labels,(d,n)->{try{if(!p.optString("kind").equals(ids[n])){p.put("kind",ids[n]).put("reviewed",false).put("recognized",false).put("answers",new JSONObject()).put("raw",new JSONObject());store.save(work);}openPage(index);}catch(Exception e){error(e);}}).show();}catch(Exception e){error(e);}}
    void recognize(int index){runBusy("Распознавание без интернета",()->{
        JSONObject p=work.getJSONArray("pages").getJSONObject(index);p.put("reviewed",false).put("recognized",false);store.save(work);File folder=store.pageDir(work,p),stage=new File(folder,"ocr-"+Store.id());stage.mkdirs();if(ocr==null)ocr=new Ocr(this);JSONObject result=ocr.process(new File(folder,"scan.jpg"),work.getString("profile"),p.getString("kind"),stage,this::progress);if(cancelled)throw new CancellationException("Распознавание остановлено");
        File[] generated=stage.listFiles();if(generated!=null)for(File f:generated){try(InputStream in=new FileInputStream(f)){Store.copy(in,new File(folder,f.getName()),20L*1024*1024);}}
        Iterator<String> fields=result.keys();while(fields.hasNext()){String key=fields.next();p.put(key,result.get(key));}
        if(p.getString("kind").equals("answers")&&!p.optBoolean("registration_link_invalid")){JSONArray pages=work.getJSONArray("pages");for(int j=index-1;j>=0;j--){JSONObject reg=pages.getJSONObject(j);if(reg.optString("kind").equals("registration")){for(String key:new String[]{"name","variant","school"})p.put(key,reg.optString(key));break;}if(Exports.answer(reg))break;}}
        store.save(work);if(generated!=null)for(File f:generated)if(f.isFile())f.delete();stage.delete();runOnUiThread(()->review(index));
    });}
    void editScan(int index){try{
        JSONObject p=work.getJSONArray("pages").getJSONObject(index);File folder=store.pageDir(work,p);Bitmap bitmap=ImageTools.load(new File(folder,"original.jpg"),3508);scanEditor(index,bitmap);
    }catch(Exception e){error(e);}}
    void scanEditor(int index,Bitmap bitmap){
        screen="crop";shell("Границы листа","Все четыре метки должны остаться внутри. Оригинал сохраняется.");CropView crop=new CropView(this,bitmap,ImageTools.detect(bitmap));body.addView(crop,new LinearLayout.LayoutParams(-1,dp(440)));
        Spinner filter=new Spinner(this);filter.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"Оригинальные цвета","Серый","Чёрно-белый"}));body.addView(filter);body.addView(text("Контраст · не стирайте тонкие минусы и запятые",13,INK));SeekBar contrast=new SeekBar(this);contrast.setMax(100);contrast.setProgress(30);body.addView(contrast);
        action("Повернуть на 90°",()->{Bitmap rotated=ImageTools.rotate(bitmap);bitmap.recycle();scanEditor(index,rotated);});action("Найти границы",()->{crop.corners=ImageTools.detect(bitmap);crop.invalidate();});action("Весь лист",()->{crop.corners=new float[]{0,0,1,0,1,1,0,1};crop.invalidate();});
        action("Предпросмотр фильтра",()->{try{Bitmap preview=ImageTools.crop(bitmap,crop.corners,filter.getSelectedItemPosition(),contrast.getProgress());new AlertDialog.Builder(this).setView(new ZoomImage(this,preview)).setPositiveButton("Закрыть",(d,w)->preview.recycle()).show();}catch(Exception e){error(e);}});
        action("Сохранить скан",()->new AlertDialog.Builder(this).setMessage("После изменения скана лист нужно распознать и сверить заново. Продолжить?").setPositiveButton("Сохранить",(d,w)->{try{Bitmap out=ImageTools.crop(bitmap,crop.corners,filter.getSelectedItemPosition(),contrast.getProgress());JSONObject p=work.getJSONArray("pages").getJSONObject(index);ImageTools.save(out,new File(store.pageDir(work,p),"scan.jpg"));out.recycle();p.put("recognized",false).put("reviewed",false);store.save(work);bitmap.recycle();openPage(index);}catch(Exception e){error(e);}}).setNegativeButton("Отмена",null).show());
        action("Назад без изменений",()->{bitmap.recycle();openPage(index);});
    }
    void review(int index){try{
        JSONObject p=work.getJSONArray("pages").getJSONObject(index);String profile=work.getString("profile"),kind=p.getString("kind");File folder=store.pageDir(work,p);screen="review";shell("Сверка · лист "+(index+1),"Скан → прочитано → правка. Ничего не отправляется в интернет.");
        if(kind.equals("manual")){image(new File(folder,"scan.jpg"),450);note("Ответы №2 не распознаются и не оцениваются автоматически. Проверьте порядок и принадлежность листа по исходной работе.");if(p.optBoolean("attachment_review_required"))note("После удаления или перестановки листов изменилось окружение этого листа. Убедитесь, что он относится к нужному ученику.");action("Лист просмотрен",()->{try{p.put("reviewed",true).put("attachment_review_required",false);store.save(work);showWork();}catch(Exception e){error(e);}});return;}
        if(!p.optBoolean("recognized")){note("Этот скан ещё не распознан. Поля можно заполнить вручную по полному изображению.");image(new File(folder,"scan.jpg"),240);}
        if(p.optBoolean("recognized"))for(int i=0;i<3;i++)image(new File(folder,"name_"+i+".png"),45);
        LinearLayout nameRow=new LinearLayout(this);nameRow.setOrientation(LinearLayout.HORIZONTAL);body.addView(nameRow);
        EditText name=input(nameRow,"ФИО ученика",p.optString("name"),false);name.setLayoutParams(new LinearLayout.LayoutParams(0,dp(54),1));
        ImageButton microphone=new ImageButton(this);microphone.setImageResource(R.drawable.ic_microphone);microphone.setBackground(bg(0xFFE6EDDF));microphone.setContentDescription("Ввести ФИО голосом без интернета");microphone.setTooltipText("ФИО голосом");nameRow.addView(microphone,new LinearLayout.LayoutParams(dp(54),dp(54)));
        if(p.optBoolean("recognized"))image(new File(folder,"region.png"),54);EditText variant=input(body,"Код региона = вариант",p.optString("variant"),false);if(p.optBoolean("recognized"))image(new File(folder,"school.png"),54);EditText school=input(body,"Код школы (если есть)",p.optString("school"),false);
        CheckBox binding=new CheckBox(this);
        if(p.optBoolean("registration_link_invalid")&&kind.equals("answers")){
            JSONObject reg=PageEdits.registrationFor(work.getJSONArray("pages"),p.getString("id"));
            note("Состав комплекта изменился. Проверьте, к какому ученику относится лист. Предыдущая регистрация: "+(reg==null?"отсутствует":reg.optString("name","ФИО не заполнено"))+". Ответы и прежние поля сохранены, автоматическая перепривязка отключена.");
            binding.setText("Подтверждаю связь с предыдущей регистрацией и ФИО со скана");body.addView(binding);
        }
        Map<Integer,EditText> fields=new LinkedHashMap<>();Map<Integer,TextView> badges=new HashMap<>();Map<Integer,TextView> expectedLabels=new HashMap<>();
        if(!kind.equals("registration"))for(int t=Profile.start(profile);t<=Profile.end(profile);t++){
            body.addView(text("Задание "+t,17,INK));if(p.optBoolean("recognized"))image(new File(folder,"answer_"+t+".png"),57);if(p.optJSONObject("confidence")!=null&&p.getJSONObject("confidence").optDouble(""+t,1)<.65)body.addView(text("Неуверенное чтение: проверьте особенно внимательно",12,RED));EditText answer=input(body,"Ответ",p.getJSONObject("answers").optString(""+t),false);fields.put(t,answer);TextView badge=text("",19,INK),expected=text("",14,INK);body.addView(badge);body.addView(expected);badges.put(t,badge);expectedLabels.put(t,expected);
        }
        Runnable compare=()->{JSONObject key=work.optJSONObject("keys").optJSONObject(Profile.variant(variant.getText().toString()));for(int task:fields.keySet()){String correct=key==null?"":key.optString(""+task),got=fields.get(task).getText().toString();TextView badge=badges.get(task);expectedLabels.get(task).setText(correct.isEmpty()?"В ключе нет ответа":"Эталон: "+correct);if(correct.isEmpty()){badge.setText("Без оценки");badge.setTextColor(0xFF69776D);}else {int points=Profile.points(profile,task,got,correct);badge.setText(points==Profile.max(profile,task)?"+ Верно":points>0?"Частично: "+points:"× Ошибка");badge.setTypeface(null,Typeface.BOLD);badge.setTextColor(points==Profile.max(profile,task)?0xFFAA7100:RED);}}};
        TextWatcher watcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}public void onTextChanged(CharSequence s,int start,int before,int count){dirty=true;compare.run();}public void afterTextChanged(Editable s){}};
        for(EditText e:fields.values())e.addTextChangedListener(watcher);name.addTextChangedListener(watcher);variant.addTextChangedListener(watcher);school.addTextChangedListener(watcher);compare.run();
        if(!kind.equals("registration")){body.addView(text("Замены и исправления ученика",18,INK));if(p.optBoolean("recognized"))image(new File(folder,"corrections.png"),130);note("Нижние замены в первой версии не применяются автоматически. Перенесите окончательные ответы в поля выше.");}
        CheckBox checked=new CheckBox(this);checked.setText(kind.equals("registration")?"ФИО, вариант и код школы сверены":"Все ответы и нижние замены сверены со сканом");checked.setChecked(p.optBoolean("reviewed"));body.addView(checked);
        microphone.setOnClickListener(v->{if(!busy)voiceInput.begin(name,()->{checked.setChecked(false);dirty=true;});});
        Runnable saveDraft=()->saveReview(index,p,name,variant,school,fields,false,checked,binding);draftSave=saveDraft;action("Сохранить черновик",saveDraft);action("Сверено · сохранить",()->saveReview(index,p,name,variant,school,fields,true,checked,binding));action("Полный скан",()->fullImage(new File(folder,"scan.jpg")));
    }catch(Exception e){error(e);}}
    void saveReview(int index,JSONObject p,EditText name,EditText variant,EditText school,Map<Integer,EditText> fields,boolean reviewed,CheckBox checked,CheckBox binding){try{
        if(reviewed&&(!checked.isChecked()||name.getText().toString().trim().isEmpty()||Profile.variant(variant.getText().toString()).isEmpty()))throw new IOException("Укажите ФИО, вариант цифрами и подтвердите сверку");
        if(reviewed&&p.optBoolean("registration_link_invalid")&&p.optString("kind").equals("answers")){
            JSONObject reg=PageEdits.registrationFor(work.getJSONArray("pages"),p.getString("id"));
            if(reg==null||!reg.optBoolean("reviewed"))throw new IOException("Перед этим листом нужна сверенная регистрация. Можно сохранить черновик, затем исправить порядок или добавить нужный лист.");
            if(!binding.isChecked())throw new IOException("Подтвердите принадлежность листа предыдущей регистрации");
            p.put("registration_link_invalid",false);
        }
        p.put("name",name.getText().toString().trim()).put("variant",variant.getText().toString().trim()).put("school",school.getText().toString().trim()).put("reviewed",reviewed);
        JSONObject answers=p.getJSONObject("answers");for(int t:fields.keySet())answers.put(""+t,fields.get(t).getText().toString().trim());
        if(p.optString("kind").equals("registration")){JSONArray pages=work.getJSONArray("pages");for(int j=index+1;j<pages.length();j++){JSONObject next=pages.getJSONObject(j);if(next.optString("kind").equals("registration"))break;if(next.optString("kind").equals("answers")){if(!next.optBoolean("registration_link_invalid"))for(String k:new String[]{"name","variant","school"})if(!next.optString(k).equals(p.optString(k))){next.put(k,p.optString(k));next.put("reviewed",false);}break;}}}
        store.save(work);dirty=false;if(reviewed)showWork();else Toast.makeText(this,"Черновик сохранён",Toast.LENGTH_SHORT).show();
    }catch(Exception e){error(e);}}
    void maskMenu(){new AlertDialog.Builder(this).setTitle("Ключ ответов").setItems(new String[]{"Загрузить XLSX или CSV","Ввести / изменить вручную"},(d,n)->{if(n==0)pick(MASK,new String[]{"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","text/csv","text/comma-separated-values","text/plain"},false);else manualMask();}).show();}
    void confirmMask(JSONObject keys){new AlertDialog.Builder(this).setTitle("Принять ключ?").setMessage("Варианты: "+keys.names()+"\nНовый ключ заменит прежний. Ответы учеников не изменятся. Результат будет пересчитан.").setPositiveButton("Принять",(d,w)->{try{work.put("keys",keys);store.save(work);showWork();}catch(Exception e){error(e);}}).setNegativeButton("Отмена",null).show();}
    void manualMask(){LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(16),0,dp(16),0);EditText variant=input(box,"Вариант (1–99)","1",false);new AlertDialog.Builder(this).setTitle("Номер варианта ключа").setView(box).setPositiveButton("Далее",(d,n)->{String v=Profile.variant(variant.getText().toString());if(v.isEmpty()){error(new IOException("Номер варианта должен содержать 1–2 цифры"));return;}editMask(v);}).setNegativeButton("Отмена",null).show();}
    void editMask(String v){try{
        screen="mask";shell("Ключ · вариант "+v,"Ответы через | означают допустимые альтернативы. Пустое поле не оценивается.");
        String profile=work.getString("profile");JSONObject old=work.getJSONObject("keys").optJSONObject(v);
        Map<Integer,EditText> fields=new LinkedHashMap<>();
        TextWatcher watcher=new TextWatcher(){
            public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){dirty=true;}
            public void afterTextChanged(Editable s){}
        };
        for(int t=Profile.start(profile);t<=Profile.end(profile);t++){
            EditText field=input(body,"Задание "+t,old==null?"":old.optString(""+t),false);
            field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(200)});
            field.addTextChangedListener(watcher);fields.put(t,field);
        }
        draftSave=()->{try{
            JSONObject key=new JSONObject();
            for(int task:fields.keySet()){
                String value=fields.get(task).getText().toString().trim();
                if(Profile.max(profile,task)==2&&!value.isEmpty())
                    for(String option:value.split("\\|"))if(!option.matches("[0-9]{5}"))throw new IOException("Задание "+task+": эталон должен содержать 5 цифр");
                if(!value.isEmpty())key.put(""+task,value);
            }
            work.getJSONObject("keys").put(v,key);store.save(work);dirty=false;
        }catch(Exception e){error(e);}};
        action("Сохранить ключ",()->{draftSave.run();if(!dirty)try{showWork();}catch(Exception e){error(e);}});
        action("Назад",this::onBackPressed);
    }catch(Exception e){error(e);}}
    void results(){try{screen="results";shell("Результаты",work.getString("title"));note("Оцениваются только сверенные ответы №1 с заполненным ключом. Развёрнутые решения и итоговую отметку проверяет учитель отдельно.");JSONArray a=work.getJSONArray("pages");for(int i=0;i<a.length();i++){JSONObject p=a.getJSONObject(i);if(Exports.answer(p))body.addView(text("Лист "+(i+1)+" · "+p.optString("name")+"\n"+Exports.score(work,p),18,INK));}action("Сохранить PDF с полными сканами",()->export("pdf"));action("Сохранить CSV для Excel",()->export("csv"));note("Экспорт содержит персональные данные и не зашифрован. Передавайте файл только нужному адресату. Это не формат обмена .blanki.");action("К работе",()->{try{showWork();}catch(Exception e){error(e);}});}catch(Exception e){error(e);}}
    void export(String type){runBusy("Подготовка "+type.toUpperCase(Locale.ROOT),()->{File d=new File(getCacheDir(),"exports");d.mkdirs();exportFile=new File(d,"blanki-"+work.getString("id").substring(0,8)+"."+type);if(type.equals("pdf")){Exports.pdf(work,store,exportFile);exportMime="application/pdf";}else{Exports.csv(work,exportFile);exportMime="text/csv";}runOnUiThread(()->{Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT);i.setType(exportMime);i.addCategory(Intent.CATEGORY_OPENABLE);i.putExtra(Intent.EXTRA_TITLE,exportFile.getName());startActivityForResult(i,SAVE_EXPORT);});});}
    void reorder(){try{JSONArray pages=work.getJSONArray("pages");String[] choices=new String[pages.length()];for(int i=0;i<choices.length;i++)choices[i]="Лист "+(i+1)+": "+kindLabel(pages.getJSONObject(i).optString("kind"));new AlertDialog.Builder(this).setTitle("Какой лист переместить?").setItems(choices,(d,index)->new AlertDialog.Builder(this).setTitle("Переместить лист").setItems(new String[]{"На одну позицию выше","На одну позицию ниже"},(dialog,direction)->{try{int target=index+(direction==0?-1:1);if(target<0||target>=pages.length())return;JSONObject temp=pages.getJSONObject(index);pages.put(index,pages.getJSONObject(target));pages.put(target,temp);for(int j=0;j<pages.length();j++)pages.getJSONObject(j).put("reviewed",false);store.save(work);showWork();}catch(Exception e){error(e);}}).show()).show();}catch(Exception e){error(e);}}
    void qaBlank(){runBusy("Проверка на пустом эталоне",()->{
        long started=System.currentTimeMillis();JSONObject report=new JSONObject().put("passed",false);
        try{
        work=store.create("QA · пустой эталон","oge_math");File file=new File(getCacheDir(),"qa.pdf");Store.copy(getAssets().open("qa/oge-math-answer1-2026.pdf"),file,10*1024*1024);importUri(Uri.fromFile(file));
        JSONObject page=work.getJSONArray("pages").getJSONObject(0);page.put("kind","oge");File folder=store.pageDir(work,page);if(ocr==null)ocr=new Ocr(this);JSONObject result=ocr.process(new File(folder,"scan.jpg"),"oge_math","oge",folder,this::progress);Iterator<String> it=result.keys();while(it.hasNext()){String key=it.next();page.put(key,result.get(key));}store.save(work);
        report=QaChecks.run(this,ocr,store,work,result);runOnUiThread(()->review(0));
        }catch(Exception e){report.put("error",e.toString());throw e;}
        finally{report.put("elapsed_ms",System.currentTimeMillis()-started);try(OutputStream out=openFileOutput("qa-report.json",MODE_PRIVATE)){out.write(report.toString().getBytes(StandardCharsets.UTF_8));}}
    });}
    static final class ZoomImage extends View {
        Bitmap bitmap;Matrix matrix=new Matrix();Paint paint=new Paint(3);ScaleGestureDetector detector;float x,y;boolean initialized=false;
        ZoomImage(Context c,Bitmap b){super(c);bitmap=b;setMinimumHeight((int)(420*c.getResources().getDisplayMetrics().density));detector=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){@Override public boolean onScale(ScaleGestureDetector d){matrix.postScale(d.getScaleFactor(),d.getScaleFactor(),d.getFocusX(),d.getFocusY());invalidate();return true;}});}
        @Override protected void onDraw(Canvas c){if(bitmap.isRecycled())return;if(!initialized&&getWidth()>0){float s=Math.min((float)getWidth()/bitmap.getWidth(),(float)getHeight()/bitmap.getHeight());matrix.setScale(s,s);matrix.postTranslate((getWidth()-bitmap.getWidth()*s)/2,(getHeight()-bitmap.getHeight()*s)/2);initialized=true;}c.drawColor(Color.WHITE);c.drawBitmap(bitmap,matrix,paint);}
        @Override public boolean onTouchEvent(MotionEvent e){detector.onTouchEvent(e);if(e.getAction()==MotionEvent.ACTION_MOVE&&!detector.isInProgress()){matrix.postTranslate(e.getX()-x,e.getY()-y);invalidate();}x=e.getX();y=e.getY();return true;}
    }
}
