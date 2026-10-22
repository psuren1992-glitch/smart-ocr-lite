package ru.blanki.mobile;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.speech.*;
import android.widget.*;
import java.util.*;

/** Uses only Android's on-device service. No network recognizer or automatic model download. */
final class NameVoiceInput {
    static final int MICROPHONE=40;
    private final Activity activity;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private SpeechRecognizer recognizer;
    private AlertDialog dialog;
    private EditText target;
    private Runnable applied;
    private int generation;
    private int permissionGeneration=-1;
    private Runnable timeout;

    NameVoiceInput(Activity activity){this.activity=activity;}

    void begin(EditText field,Runnable onApplied) {
        cancel();
        if(Build.VERSION.SDK_INT<31) {
            explain("Безопасный офлайн-ввод этой кнопкой доступен с Android 12. На этом телефоне используйте обычное поле ФИО.");return;
        }
        try {
            if(!SpeechRecognizer.isOnDeviceRecognitionAvailable(activity)) {
                explain("На телефоне нет встроенного офлайн-распознавателя речи. ФИО можно ввести вручную. Онлайн-сервис не будет запущен.");return;
            }
        }catch(RuntimeException e){explain("Не удалось проверить офлайн-распознаватель телефона. ФИО можно ввести вручную; онлайн-сервис не используется.");return;}
        target=field;applied=onApplied;
        if(activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED) {
            permissionGeneration=generation;
            activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},MICROPHONE);return;
        }
        listen();
    }

    void permissionResult(int request,int[] grants) {
        if(request!=MICROPHONE||permissionGeneration!=generation)return;
        permissionGeneration=-1;
        if(grants.length>0&&grants[0]==PackageManager.PERMISSION_GRANTED&&current())listen();
        else {cancel();explain("Доступ к микрофону не предоставлен. ФИО осталось без изменений; его можно заполнить вручную.");}
    }

    private boolean current(){return target!=null&&target.isAttachedToWindow()&&!activity.isFinishing()&&!activity.isDestroyed();}
    private boolean current(int token){return token==generation&&current();}

    private void listen() {
        if(Build.VERSION.SDK_INT<31||!current())return;
        final int token=generation;
        Intent intent=new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE,"ru-RU")
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE,true)
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,3)
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,true);
        dialog=new AlertDialog.Builder(activity).setTitle("ФИО голосом · без интернета")
            .setMessage("Проверяю русский офлайн-пакет…")
            .setNegativeButton("Отмена",(d,w)->cancel())
            .setPositiveButton("Готово",null).create();
        dialog.setOnCancelListener(d->cancel());dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            if(recognizer!=null&&current(token)) {
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
                dialog.setMessage("Завершаю распознавание…");
                try{recognizer.stopListening();}catch(RuntimeException e){fail("Не удалось завершить голосовой ввод. ФИО не изменено.");}
            }
        });
        timeout=()->{if(current(token))fail("Голосовой ввод не ответил вовремя. ФИО не изменено. Попробуйте ещё раз.");};
        handler.postDelayed(timeout,30000);
        try {
            recognizer=SpeechRecognizer.createOnDeviceSpeechRecognizer(activity);
            recognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params){if(current(token)&&dialog!=null){dialog.setMessage("Скажите фамилию, имя и отчество. Затем нажмите «Готово» или немного подождите.");dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);}}
                @Override public void onBeginningOfSpeech(){}
                @Override public void onRmsChanged(float rms){}
                @Override public void onBufferReceived(byte[] buffer){}
                @Override public void onEndOfSpeech(){if(current(token)&&dialog!=null)dialog.setMessage("Распознаю ФИО на телефоне…");}
                @Override public void onError(int error){if(current(token))fail(errorMessage(error));}
                @Override public void onResults(Bundle result){if(current(token))offer(VoiceNames.candidates(result==null?null:result.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)));}
                @Override public void onPartialResults(Bundle result){if(current(token)&&dialog!=null&&result!=null){List<String> names=VoiceNames.candidates(result.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION));if(!names.isEmpty())dialog.setMessage("Слышу: "+names.get(0)+"\n\nФИО пока не изменено.");}}
                @Override public void onEvent(int type,Bundle params){}
            });
            if(Build.VERSION.SDK_INT>=33)checkLanguage(intent,token);else start(intent,token);
        }catch(RuntimeException e){fail("Не удалось запустить офлайн-распознавание. Проверьте микрофон и наличие русского офлайн-пакета в настройках телефона.");}
    }

    @androidx.annotation.RequiresApi(33)
    private void checkLanguage(Intent intent,int token) {
        recognizer.checkRecognitionSupport(intent,activity.getMainExecutor(),new RecognitionSupportCallback(){
            @Override public void onSupportResult(RecognitionSupport support) {
                if(!current(token))return;
                String language=VoiceNames.russianLanguage(support.getInstalledOnDeviceLanguages());
                if(language.isEmpty()){fail("Русский офлайн-пакет речи не установлен или не поддерживается. ФИО не изменено. Проверьте языки офлайн-распознавания в настройках телефона; приложение ничего не скачивает автоматически.");return;}
                intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE,language);start(intent,token);
            }
            @Override public void onError(int error) {
                if(!current(token))return;
                if(error==SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT)start(intent,token);
                else fail(errorMessage(error));
            }
        });
    }

    private void start(Intent intent,int token) {
        if(!current(token)||recognizer==null)return;
        try {recognizer.startListening(intent);}
        catch(RuntimeException e){fail("Микрофон недоступен. ФИО не изменено; повторите попытку или введите его вручную.");}
    }

    private void offer(List<String> names) {
        if(names.isEmpty()){fail("Не удалось разобрать ФИО. Поле не изменено.");return;}
        EditText field=target;Runnable action=applied;cancel();
        target=field;applied=action;int token=generation;
        LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.VERTICAL);
        int padding=(int)(20*activity.getResources().getDisplayMetrics().density);box.setPadding(padding,0,padding,0);
        TextView hint=new TextView(activity);hint.setText("Проверьте имя со сканом. Замена произойдёт только после подтверждения.");box.addView(hint);
        EditText proposed=new EditText(activity);proposed.setText(names.get(0));proposed.setTextSize(18);proposed.setSingleLine(true);
        proposed.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(200)});box.addView(proposed);
        if(names.size()>1)for(int i=1;i<names.size();i++){String candidate=names.get(i);Button choice=new Button(activity);choice.setAllCaps(false);choice.setText(candidate);choice.setOnClickListener(v->proposed.setText(candidate));box.addView(choice);}
        dialog=new AlertDialog.Builder(activity).setTitle("Подставить это ФИО?").setView(box)
            .setNegativeButton("Отмена",(d,w)->cancel()).setPositiveButton("Подставить",null).create();
        dialog.setOnCancelListener(d->cancel());dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            String value=VoiceNames.clean(proposed.getText().toString());
            if(value.isEmpty()){proposed.setError("Укажите ФИО");return;}
            if(current(token)){field.setText(value);field.setSelection(field.length());if(action!=null)action.run();}
            cancel();
        });
    }

    static String errorMessage(int error) {
        return switch(error) {
            case SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> "Русская речь недоступна офлайн. Проверьте русский офлайн-пакет в настройках телефона. ФИО не изменено.";
            case SpeechRecognizer.ERROR_NO_MATCH,SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Речь не удалось разобрать. Скажите ФИО ещё раз. Поле не изменено.";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Для голосового ввода нужен доступ к микрофону. ФИО не изменено.";
            default -> "Офлайн-ввод сейчас недоступен. Попробуйте ещё раз или введите ФИО вручную. Онлайн-сервис не используется.";
        };
    }

    private void fail(String message){cancel();explain(message);}
    private void explain(String message){if(!activity.isFinishing()&&!activity.isDestroyed())new AlertDialog.Builder(activity).setTitle("Голосовой ввод").setMessage(message).setPositiveButton("Понятно",null).show();}
    void cancel() {
        generation++;permissionGeneration=-1;
        if(timeout!=null){handler.removeCallbacks(timeout);timeout=null;}
        SpeechRecognizer old=recognizer;recognizer=null;
        if(old!=null){try{old.cancel();}catch(RuntimeException ignored){}try{old.destroy();}catch(RuntimeException ignored){}}
        AlertDialog oldDialog=dialog;dialog=null;if(oldDialog!=null)oldDialog.dismiss();
        target=null;applied=null;
    }
}
