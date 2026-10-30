using System.IO.Compression;
using System.Text;
using System.Xml;
using UglyToad.PdfPig;
using UglyToad.PdfPig.DocumentLayoutAnalysis.TextExtractor;
using UglyToad.PdfPig.Exceptions;

namespace IraKit.Tools;

/// <summary>The text of a file Ira was asked to read: PDF, Word (.docx), RTF, plain text or Markdown.</summary>
internal static class FileText
{
    public sealed record Read(string Text, string Kind, bool Truncated, int? Pages = null);

    /// <summary>The most a file may weigh before Ira refuses to open it.</summary>
    public const long MaxFileBytes = 64L * 1024 * 1024;

    /// <summary>The most a Word file's text part may unpack to (a zip bomb stops here).</summary>
    private const long MaxUnpackedBytes = 64L * 1024 * 1024;

    public static readonly HashSet<string> PlainExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "txt", "text", "md", "markdown", "mdown", "csv", "tsv", "json", "log", "yaml", "yml",
        "xml", "html", "htm", "srt", "vtt", "tex", "ini", "toml",
    };

    public static Read ReadFile(string path, int maxChars)
    {
        if (Directory.Exists(path)) throw new ToolFailure("that is a folder; ask me to find files in it instead");
        var info = new FileInfo(path);
        if (!info.Exists) throw new ToolFailure("there is no file at that path");
        if (info.Length > MaxFileBytes) throw new ToolFailure("that file is larger than 64 MB; I read smaller files only");

        var ext = info.Extension.TrimStart('.').ToLowerInvariant();
        try
        {
            return ext switch
            {
                "pdf" => Pdf(path, maxChars),
                "docx" => Cut(Docx(path), "Word document", maxChars),
                "rtf" => Cut(Rtf(File.ReadAllText(path, Encoding.Latin1)), "RTF document", maxChars),
                _ when PlainExtensions.Contains(ext) => Cut(Plain(path), KindName(ext), maxChars),
                _ => throw new ToolFailure(
                    $"I can read PDF, Word (.docx), RTF, text and Markdown files, not .{(ext.Length == 0 ? "this kind of" : ext)} files"),
            };
        }
        catch (UnauthorizedAccessException)
        {
            throw new ToolFailure("Windows did not let me open that file");
        }
        catch (IOException)
        {
            throw new ToolFailure("that file is in use or could not be read; close it in its app and ask again");
        }
    }

    public static string KindName(string ext) => ext switch
    {
        "md" or "markdown" or "mdown" => "Markdown",
        "csv" or "tsv" => "table (CSV)",
        "html" or "htm" => "web page",
        _ => "text",
    };

    /// <summary>Text cut to <paramref name="maxChars"/>, at a line or word end when one is near.</summary>
    public static Read Cut(string text, string kind, int maxChars, int? pages = null)
    {
        text = text.Replace("\r\n", "\n").Trim();
        if (text.Length <= maxChars) return new Read(text, kind, false, pages);
        var cut = text[..maxChars];
        var end = Math.Max(cut.LastIndexOf('\n'), cut.LastIndexOf(' '));
        if (end > maxChars * 0.8) cut = cut[..end];
        return new Read(cut.TrimEnd(), kind, true, pages);
    }

    private static Read Pdf(string path, int maxChars)
    {
        PdfDocument document;
        try
        {
            document = PdfDocument.Open(path);
        }
        catch (PdfDocumentEncryptedException)
        {
            throw new ToolFailure("that PDF is locked with a password; I can't read it");
        }
        catch (UglyToad.PdfPig.Core.PdfDocumentFormatException)
        {
            throw new ToolFailure("that PDF looks damaged; I can't read it");
        }
        using (document)
        {
            var text = new StringBuilder();
            foreach (var page in document.GetPages())
            {
                text.Append(ContentOrderTextExtractor.GetText(page)).Append("\n\n");
                if (text.Length > maxChars) break;
            }
            if (string.IsNullOrWhiteSpace(text.ToString()))
                throw new ToolFailure("that PDF has no text I can read; it may be a scan (a picture of pages)");
            return Cut(text.ToString(), "PDF", maxChars, document.NumberOfPages);
        }
    }

    /// <summary>A .docx is a zip; its text is in word/document.xml, paragraph by paragraph.</summary>
    internal static string Docx(string path)
    {
        using var zip = ZipFile.OpenRead(path);
        var entry = zip.GetEntry("word/document.xml") ?? throw new ToolFailure("that Word file has no text part");
        if (entry.Length > MaxUnpackedBytes) throw new ToolFailure("that Word file unpacks to too much text");
        using var stream = entry.Open();
        using var reader = XmlReader.Create(stream, new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaxUnpackedBytes,
        });
        const string word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
        var text = new StringBuilder();
        while (reader.Read())
        {
            if (reader.NamespaceURI != word) continue;
            if (reader.NodeType == XmlNodeType.Element)
            {
                switch (reader.LocalName)
                {
                    case "t": text.Append(reader.ReadElementContentAsString()); break;
                    case "tab": text.Append('\t'); break;
                    case "br" or "cr": text.Append('\n'); break;
                }
            }
            else if (reader.NodeType == XmlNodeType.EndElement && reader.LocalName == "p")
            {
                text.Append('\n');
            }
        }
        return text.ToString();
    }

    /// <summary>
    /// RTF's words without its markup: control words dropped, the header's tables skipped,
    /// paragraph and tab marks kept, and escaped characters (<c>\'e9</c>, <c>—?</c>) decoded.
    /// </summary>
    internal static string Rtf(string rtf)
    {
        var text = new StringBuilder();
        var skip = new Stack<bool>();
        var skipping = false;
        var skipNext = 0; // the fallback characters after \uN
        for (var i = 0; i < rtf.Length; i++)
        {
            var c = rtf[i];
            if (c == '{')
            {
                skip.Push(skipping);
                // A destination to leave out: {\* ...} and the header tables.
                var rest = rtf.AsSpan(i + 1);
                if (rest.StartsWith(@"\*") || rest.StartsWith(@"\fonttbl") || rest.StartsWith(@"\colortbl")
                    || rest.StartsWith(@"\stylesheet") || rest.StartsWith(@"\info") || rest.StartsWith(@"\pict"))
                {
                    skipping = true;
                }
                continue;
            }
            if (c == '}')
            {
                skipping = skip.Count > 0 && skip.Pop();
                continue;
            }
            if (c == '\\' && i + 1 < rtf.Length)
            {
                var next = rtf[i + 1];
                if (next is '\\' or '{' or '}')
                {
                    if (!skipping) text.Append(next);
                    i++;
                    continue;
                }
                if (next == '\'' && i + 3 < rtf.Length)
                {
                    if (!skipping && skipNext == 0
                        && byte.TryParse(rtf.AsSpan(i + 2, 2), System.Globalization.NumberStyles.HexNumber, null, out var b))
                    {
                        text.Append(Encoding.Latin1.GetString([b]));
                    }
                    if (skipNext > 0) skipNext--;
                    i += 3;
                    continue;
                }
                var start = i + 1;
                var end = start;
                while (end < rtf.Length && char.IsAsciiLetter(rtf[end])) end++;
                var name = rtf[start..end];
                var numberStart = end;
                if (end < rtf.Length && rtf[end] == '-') end++;
                while (end < rtf.Length && char.IsAsciiDigit(rtf[end])) end++;
                var number = rtf[numberStart..end];
                if (end < rtf.Length && rtf[end] == ' ') end++;
                i = end - 1;
                if (skipping) continue;
                switch (name)
                {
                    case "par" or "line" or "row": text.Append('\n'); break;
                    case "tab" or "cell": text.Append('\t'); break;
                    case "u" when int.TryParse(number, out var code):
                        text.Append((char)(code < 0 ? code + 65536 : code));
                        skipNext = 1;
                        break;
                }
                continue;
            }
            if (skipping || c is '\r' or '\n') continue;
            if (skipNext > 0)
            {
                skipNext--;
                continue;
            }
            text.Append(c);
        }
        return text.ToString();
    }

    private static string Plain(string path)
    {
        var bytes = File.ReadAllBytes(path);
        if (bytes.AsSpan(0, Math.Min(bytes.Length, 8192)).IndexOf((byte)0) >= 0
            && !(bytes.Length >= 2 && (bytes[0], bytes[1]) is (0xFF, 0xFE) or (0xFE, 0xFF)))
        {
            throw new ToolFailure("that file is not text");
        }
        using var reader = new StreamReader(new MemoryStream(bytes), new UTF8Encoding(false), detectEncodingFromByteOrderMarks: true);
        return reader.ReadToEnd();
    }
}
