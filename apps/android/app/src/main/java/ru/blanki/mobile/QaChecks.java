package ru.blanki.mobile;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.os.ParcelFileDescriptor;
import org.json.*;
import org.opencv.core.*;
import org.opencv.imgproc.Imgproc;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.zip.*;

/** Debug-only entry point uses bundled blank forms and synthetic data, never user files. */
final class QaChecks {
    static void require(boolean ok,String message)throws IOException {
        if(!ok)throw new IOException("QA: "+message);
    }

    static JSONObject run(Context context,Ocr ocr,Store store,JSONObject work,JSONObject result)throws Exception {
        JSONObject report=new JSONObject();
        JSONObject answers=result.getJSONObject("answers");
        require(answers.length()==19,"ожидалось 19 ответов ОГЭ");
        for(int t=1;t<=19;t++)require(answers.getString(""+t).isEmpty(),"на пустом бланке прочитан ответ "+t);
        require(!result.getBoolean("reviewed"),"OCR не должен подтверждать сверку");
        report.put("blank_answers",19).put("blank_false_answers",0);

        Mat row=new Mat(80,320,CvType.CV_8UC1,new Scalar(255));
        try {
            Imgproc.putText(row,"-0,68",new Point(10,58),Imgproc.FONT_HERSHEY_SIMPLEX,1.6,new Scalar(0),2);
            String prediction=ocr.modelText(row);
            require(!prediction.isEmpty(),"ONNX вернул пустую строку на печатном тесте");
            report.put("synthetic_print_prediction",prediction).put("onnx_inference",true);
        } finally {row.release();}

        String xml="<?xml version=\"1.0\" encoding=\"UTF-8\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>"
            +"<row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>№ задания</t></is></c><c r=\"B1\" t=\"inlineStr\"><is><t>Вариант 1</t></is></c></row>"
            +"<row r=\"2\"><c r=\"A2\"><v>1</v></c><c r=\"B2\" t=\"inlineStr\"><is><t>-0,68</t></is></c></row></sheetData></worksheet>";
        JSONObject keys=MaskReader.parse(MaskReader.xlsx(new ByteArrayInputStream(sheetArchive(xml))),"oge_math");
        require(keys.getJSONObject("1").getString("1").equals("-0,68"),"XLSX потерял минус или запятую");
        boolean rejected=false;
        try {MaskReader.xlsx(new ByteArrayInputStream(sheetArchive(xml.replace("<v>1</v>","<f>1+0</f><v>1</v>"))));}
        catch(IOException expected){rejected=true;}
        require(rejected,"формулы XLSX не отклонены");
        report.put("xlsx_import",true).put("xlsx_formula_rejected",true);

        JSONObject page=work.getJSONArray("pages").getJSONObject(0);
        JSONObject persisted=store.load(work.getString("id"));
        require(!persisted.getJSONArray("pages").getJSONObject(0).getBoolean("reviewed"),"не сохранён статус OCR");
        File output=new File(context.getCacheDir(),"qa-exports");output.mkdirs();
        // Export a copy, so the visible blank test stays unreviewed.
        JSONObject demo=new JSONObject(work.toString());
        JSONObject demoPage=demo.getJSONArray("pages").getJSONObject(0);
        demoPage.put("reviewed",true).put("name","ТЕСТОВЫЙ УЧЕНИК").put("variant","1");
        demo.put("keys",keys);
        File csv=Exports.csv(demo,new File(output,"blank.csv"));
        File pdf=Exports.pdf(demo,store,new File(output,"blank.pdf"));
        try(ParcelFileDescriptor fd=ParcelFileDescriptor.open(pdf,ParcelFileDescriptor.MODE_READ_ONLY);
            PdfRenderer renderer=new PdfRenderer(fd)) {
            require(renderer.getPageCount()==2,"в PDF должен быть отчёт и полный скан");
            for(int i=0;i<renderer.getPageCount();i++) {
                try(PdfRenderer.Page pdfPage=renderer.openPage(i)) {
                    Bitmap bitmap=Bitmap.createBitmap(595,842,Bitmap.Config.ARGB_8888);
                    bitmap.eraseColor(Color.WHITE);
                    try {pdfPage.render(bitmap,null,null,PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);}
                    finally {bitmap.recycle();}
                }
            }
            report.put("pdf_pages",renderer.getPageCount());
        }
        require(csv.length()>100,"пустой CSV");
        report.put("csv_export",true).put("persistence",true).put("work_id",work.getString("id"));
        report.put("reviewed",page.getBoolean("reviewed")).put("passed",true);
        return report;
    }

    static byte[] sheetArchive(String xml)throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(ZipOutputStream zip=new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("xl/worksheets/sheet1.xml"));
            zip.write(xml.getBytes(StandardCharsets.UTF_8));zip.closeEntry();
        }
        return bytes.toByteArray();
    }
}
