package io.github.helloupendra.ira.core

import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeParseException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/** A tool could not do what was asked; the message is safe to send to the server. */
class ToolFailure(message: String) : Exception(message)

/**
 * A tool's arguments, checked. The model wrote them, so each tool validates its own:
 * types, lengths, ranges and formats, with a plain message when something is wrong.
 */
class Args(private val raw: JsonObject) {
    fun string(name: String, max: Int, required: Boolean = false): String? {
        val value = raw[name]
        if (value == null || value is kotlinx.serialization.json.JsonNull) {
            if (required) throw ToolFailure("'$name' is needed")
            return null
        }
        val text = (value as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()
            ?: throw ToolFailure("'$name' must be text")
        if (text.isEmpty()) {
            if (required) throw ToolFailure("'$name' is empty")
            return null
        }
        if (text.length > max) throw ToolFailure("'$name' is longer than $max characters")
        return text
    }

    fun int(name: String, min: Int, max: Int, default: Int? = null): Int? {
        val value = raw[name] ?: return default
        if (value is kotlinx.serialization.json.JsonNull) return default
        val prim = value as? JsonPrimitive ?: throw ToolFailure("'$name' must be a number")
        val number = (if (prim.isString) prim.content.trim().toDoubleOrNull() else prim.doubleOrNull)
            ?: throw ToolFailure("'$name' must be a number")
        if (number != Math.floor(number)) throw ToolFailure("'$name' must be a whole number")
        if (number < min || number > max) throw ToolFailure("'$name' must be from $min to $max")
        return number.toInt()
    }

    fun requireInt(name: String, min: Int, max: Int): Int = int(name, min, max) ?: throw ToolFailure("'$name' is needed")

    fun bool(name: String): Boolean? {
        val prim = raw[name] as? JsonPrimitive ?: return null
        return prim.booleanOrNull ?: prim.content.lowercase().let {
            when (it) {
                "true", "yes" -> true
                "false", "no" -> false
                else -> throw ToolFailure("'$name' must be true or false")
            }
        }
    }

    fun choice(name: String, options: List<String>, default: String? = null): String? {
        val value = string(name, 40)?.lowercase() ?: return default
        if (value !in options) throw ToolFailure("'$name' must be one of ${options.joinToString(", ")}")
        return value
    }

    fun list(name: String): List<String> {
        val value = raw[name] ?: return emptyList()
        val array = value as? JsonArray ?: throw ToolFailure("'$name' must be a list")
        return array.map {
            (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content ?: throw ToolFailure("'$name' must list text")
        }
    }

    companion object {
        val DAYS = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun")

        /**
         * A phone number as the phone dials it: digits, an optional leading +, and nothing
         * else (spaces, dashes, dots and brackets are dropped). Three to 20 digits.
         */
        fun phoneNumber(value: String): String {
            val trimmed = value.trim()
            if (!Regex("^\\+?[0-9 ()./-]{3,30}$").matches(trimmed)) {
                throw ToolFailure("'$value' is not a phone number")
            }
            val digits = trimmed.filter { it.isDigit() }
            if (digits.length !in 3..20) throw ToolFailure("'$value' is not a phone number")
            return (if (trimmed.startsWith("+")) "+" else "") + digits
        }

        /** The last digits of a number, for matching "98100 00000" with "+919810000000". */
        fun numberKey(value: String, digits: Int = 10): String = value.filter { it.isDigit() }.takeLast(digits)

        fun localDateTime(value: String, name: String = "at"): LocalDateTime =
            try {
                LocalDateTime.parse(value.trim().replace(' ', 'T'))
            } catch (_: DateTimeParseException) {
                throw ToolFailure("'$name' must be a local date and time, YYYY-MM-DDTHH:MM")
            }

        fun localDate(value: String, name: String = "date"): LocalDate =
            try {
                LocalDate.parse(value.trim())
            } catch (_: DateTimeParseException) {
                throw ToolFailure("'$name' must be a date, YYYY-MM-DD")
            }

        fun dayOfWeek(day: String): DayOfWeek =
            when (day.lowercase()) {
                "mon" -> DayOfWeek.MONDAY
                "tue" -> DayOfWeek.TUESDAY
                "wed" -> DayOfWeek.WEDNESDAY
                "thu" -> DayOfWeek.THURSDAY
                "fri" -> DayOfWeek.FRIDAY
                "sat" -> DayOfWeek.SATURDAY
                "sun" -> DayOfWeek.SUNDAY
                else -> throw ToolFailure("days are mon, tue, wed, thu, fri, sat, sun")
            }
    }
}
